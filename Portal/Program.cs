using WebSite.Data;
using GridWitness.Portal.Services;
using GridWitness.Portal.Services.Security;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.HttpOverrides;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Identity.UI.Services;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;

var builder = WebApplication.CreateBuilder(args);

// Behind the shared host nginx (TLS terminator). Honour X-Forwarded-Proto/For so the app knows it is
// served over https at gridwitness.twinscrollgridbalancer.co.uk — email-confirmation links and secure
// cookies then use the real scheme/host. The published port is loopback-only, so only nginx can reach
// it; clearing KnownNetworks/Proxies to trust the immediate hop is safe here.
builder.Services.Configure<ForwardedHeadersOptions>(o =>
{
    o.ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedProto;
    o.KnownNetworks.Clear();
    o.KnownProxies.Clear();
});

// ---- Database + Identity: SHARED estate SSO (accounts only; nodes/tokens live in the Python server) ----
// The Identity store is the shared estate DB (SQL Server) in production, or a standalone SQLite file in
// dev. PortalDbContext declares no tables of its own, and Database:ManageSchema=false in prod, so the
// portal never migrates the shared Identity tables — TSGBWebsite owns them.
var connectionString = builder.Configuration.GetConnectionString("DefaultConnection")
    ?? "Data Source=App_Data/portal.db";
var dbProvider = builder.Configuration["Database:Provider"] ?? "Sqlite";
builder.Services.AddDbContext<ApplicationDbContext>(options =>
{
    if (string.Equals(dbProvider, "SqlServer", StringComparison.OrdinalIgnoreCase))
        options.UseSqlServer(connectionString);
    else
        options.UseSqlite(connectionString);
    // EF Core 10 raises PendingModelChangesWarning from Migrate() as a false positive; ignore it so a
    // standalone dev DB can migrate cleanly.
    options.ConfigureWarnings(w => w.Ignore(RelationalEventId.PendingModelChangesWarning));
});
builder.Services.AddDatabaseDeveloperPageExceptionFilter();

// ---- Shared DataProtection key ring: one login valid across the whole estate ----
// Every estate app must share the SAME key ring, the SAME application name, and issue the auth cookie
// on the SAME parent domain. In prod the ring is a bind-mounted folder (Auth:KeysDirectory, read-only);
// in dev it falls back to App_Data/keys and the blank cookie domain keeps localhost host-only.
var appName = builder.Configuration["Auth:ApplicationName"];
if (string.IsNullOrWhiteSpace(appName)) appName = "TSGBWebsite";
var keysDir = builder.Configuration["Auth:KeysDirectory"];
if (string.IsNullOrWhiteSpace(keysDir))
    keysDir = Path.Combine(builder.Environment.ContentRootPath, "App_Data", "keys");
Directory.CreateDirectory(keysDir);
builder.Services.AddDataProtection()
    .PersistKeysToFileSystem(new DirectoryInfo(keysDir))
    .SetApplicationName(appName);

// RequireConfirmedAccount = false: registration is open and nobody is forced to confirm their email.
// Confirmation is instead enforced at the GDPR rights actions (alter consent / erase data) in the
// dashboard, because a confirmed email is the proof of ownership we need before acting on your data.
builder.Services.AddDefaultIdentity<IdentityUser>(options =>
    {
        options.SignIn.RequireConfirmedAccount = false;
        options.Password.RequiredLength = 8;
    })
    .AddEntityFrameworkStores<ApplicationDbContext>();

// ---- Auth cookie: cross-subdomain SSO ----
// The cookie name MUST match the estate's Identity cookie and, for SSO, the Domain MUST be the shared
// parent (.twinscrollgridbalancer.co.uk). Both config-driven, so localhost dev stays host-only.
builder.Services.ConfigureApplicationCookie(options =>
{
    var cookieName = builder.Configuration["Auth:CookieName"];
    if (!string.IsNullOrWhiteSpace(cookieName)) options.Cookie.Name = cookieName;
    var cookieDomain = builder.Configuration["Auth:CookieDomain"];
    if (!string.IsNullOrWhiteSpace(cookieDomain)) options.Cookie.Domain = cookieDomain;
    options.Cookie.SameSite = SameSiteMode.Lax;
    options.Cookie.SecurePolicy = CookieSecurePolicy.SameAsRequest;
    options.SlidingExpiration = true;
});

// ---- MVC + Razor Pages (the default Identity UI is Razor Pages) ----
builder.Services.AddControllersWithViews();
builder.Services.AddRazorPages();

// ---- Email (MailKit; logs the confirmation link in dev when SMTP is unset) ----
builder.Services.Configure<SmtpSettings>(builder.Configuration.GetSection("Smtp"));
builder.Services.AddSingleton<IEmailSender, SmtpEmailSender>();

// ---- Ingest admin client: the bridge to the Python ingest server ----
// Base URL and internal credential come from config, overridable by the GW_* env vars the compose
// stack sets (so the same secret is shared with the Python container over the private network).
var ingestBase = Environment.GetEnvironmentVariable("GW_INGEST_BASE")
    ?? builder.Configuration["Ingest:BaseUrl"] ?? "http://localhost:8000";
var internalKey = Environment.GetEnvironmentVariable("GW_INTERNAL_KEY")
    ?? builder.Configuration["Ingest:InternalKey"] ?? "";
builder.Services.AddHttpClient<IngestAdminClient>(client =>
{
    client.BaseAddress = new Uri(ingestBase);
    client.Timeout = TimeSpan.FromSeconds(15);
    if (!string.IsNullOrEmpty(internalKey))
        client.DefaultRequestHeaders.Add("X-GW-Internal", internalKey);
});

// ---- Bulk client: survey-file upload + account data export ----
// Same private credential, but a much longer timeout — these carry up to 100 files / a whole export
// zip, far too slow for the 15s admin timeout above.
builder.Services.AddHttpClient<IngestBulkClient>(client =>
{
    client.BaseAddress = new Uri(ingestBase);
    client.Timeout = TimeSpan.FromMinutes(10);
    if (!string.IsNullOrEmpty(internalKey))
        client.DefaultRequestHeaders.Add("X-GW-Internal", internalKey);
});

// ---- Upload size limits (none existed before the survey feature) ----
// A survey batch is up to 100 analyser files. Raise the multipart form limit to match the ~600 MB
// batch ceiling the UploadController enforces; nginx client_max_body_size upstream must match (deploy).
builder.Services.Configure<Microsoft.AspNetCore.Http.Features.FormOptions>(o =>
{
    o.MultipartBodyLengthLimit = 600_000_000;   // ~600 MB
    o.ValueLengthLimit = int.MaxValue;
});
builder.WebHost.ConfigureKestrel(o => o.Limits.MaxRequestBodySize = 600_000_000);

// ---- JS/CSS/HTML minification (same toolchain as TSGBWebsite) ----
var bundlingEnabled = builder.Configuration.GetValue("Bundling:Enabled", true);
if (bundlingEnabled)
{
    builder.Services.AddWebOptimizer(pipeline =>
    {
        pipeline.MinifyJsFiles();
        pipeline.MinifyCssFiles();
        pipeline.MinifyHtmlFiles();
    });
}

var app = builder.Build();

// ---- Schema: only manage it when we own the DB (standalone dev). On the shared estate DB,
// Database:ManageSchema=false so the portal NEVER migrates the Identity tables TSGBWebsite owns. ----
Directory.CreateDirectory(Path.Combine(app.Environment.ContentRootPath, "App_Data"));
if (app.Configuration.GetValue("Database:ManageSchema", true))
{
    using var scope = app.Services.CreateScope();
    var db = scope.ServiceProvider.GetRequiredService<ApplicationDbContext>();
    // The unified Estate.Data migration set targets SQL Server; standalone SQLite
    // dev builds the schema directly from the model instead.
    if (db.Database.IsSqlite())
        db.Database.EnsureCreated();
    else
        db.Database.Migrate();
}
else
{
    app.Logger.LogInformation("Identity schema managed externally (Database:ManageSchema=false) — shared estate DB.");
}

// ---- HTTP pipeline ----
app.UseForwardedHeaders();

if (app.Environment.IsDevelopment())
{
    app.UseMigrationsEndPoint();
}
else
{
    app.UseExceptionHandler("/Home/Error");
    app.UseHsts();
    app.UseHttpsRedirection();
}

app.UseRouting();
app.UseAuthentication();
app.UseAuthorization();

// Cross-subdomain SSO guard: bounce already-signed-in users off the Identity Register/Login forms so
// the shared auth cookie can't trip antiforgery's user-binding on submit. AFTER auth, BEFORE endpoints.
app.UseAuthenticatedIdentityFormsRedirect();

if (bundlingEnabled)
{
    app.UseWebOptimizer();
}

app.MapStaticAssets();

app.MapControllerRoute(
        name: "default",
        pattern: "{controller=Home}/{action=Index}/{id?}")
    .WithStaticAssets();
app.MapRazorPages()
   .WithStaticAssets();

app.Run();
