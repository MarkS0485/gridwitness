using GridWitness.Portal.Data;
using GridWitness.Portal.Services;
using Microsoft.AspNetCore.HttpOverrides;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Identity.UI.Services;
using Microsoft.EntityFrameworkCore;

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

// ---- Database + Identity (accounts only; nodes/tokens live in the Python server) ----
var connectionString = builder.Configuration.GetConnectionString("DefaultConnection")
    ?? "Data Source=App_Data/portal.db";
builder.Services.AddDbContext<PortalDbContext>(options => options.UseSqlite(connectionString));
builder.Services.AddDatabaseDeveloperPageExceptionFilter();

// RequireConfirmedAccount = false: registration is open and nobody is forced to confirm their email.
// Confirmation is instead enforced at the GDPR rights actions (alter consent / erase data) in the
// dashboard, because a confirmed email is the proof of ownership we need before acting on your data.
builder.Services.AddDefaultIdentity<IdentityUser>(options =>
    {
        options.SignIn.RequireConfirmedAccount = false;
        options.Password.RequiredLength = 8;
    })
    .AddEntityFrameworkStores<PortalDbContext>();

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

// ---- Ensure the SQLite directory exists, then apply migrations at startup (idempotent) ----
Directory.CreateDirectory(Path.Combine(app.Environment.ContentRootPath, "App_Data"));
using (var scope = app.Services.CreateScope())
{
    var db = scope.ServiceProvider.GetRequiredService<PortalDbContext>();
    db.Database.Migrate();
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
