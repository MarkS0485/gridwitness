namespace GridWitness.Portal.Services.Security;

/// <summary>
/// Sends users who already have a valid authenticated session away from the Identity
/// Register/Login forms (redirect to a safe local return URL, else home) instead of
/// letting them submit.
///
/// Why this exists: the portal now shares ONE Identity auth cookie with the rest of the
/// estate across <c>*.twinscrollgridbalancer.co.uk</c> (cross-subdomain SSO). ASP.NET
/// Core's antiforgery token is bound to the request's user identity, so when the shared
/// cookie authenticates a request whose Register/Login form was minted for a different
/// (or anonymous) user, antiforgery rejects the POST with HTTP 400 — the "sign-in is
/// broken" symptom for already-signed-in visitors. Short-circuiting authenticated users
/// off these endpoints BEFORE the antiforgery filter runs prevents the 400 on every path.
///
/// MUST be registered AFTER <c>UseAuthentication()</c> so <c>HttpContext.User</c> is populated.
/// </summary>
public sealed class AuthenticatedIdentityFormsRedirectMiddleware
{
    private readonly RequestDelegate _next;

    private static readonly PathString[] GuardedPaths =
    {
        new("/Identity/Account/Register"),
        new("/Identity/Account/Login"),
    };

    public AuthenticatedIdentityFormsRedirectMiddleware(RequestDelegate next) => _next = next;

    public async Task InvokeAsync(HttpContext ctx)
    {
        if (ctx.User?.Identity?.IsAuthenticated == true && IsGuarded(ctx.Request.Path))
        {
            ctx.Response.Redirect(SafeLocalReturnUrl(ctx.Request.Query["returnUrl"]));
            return;
        }

        await _next(ctx);
    }

    private static bool IsGuarded(PathString path)
    {
        foreach (var guarded in GuardedPaths)
            if (path.StartsWithSegments(guarded, StringComparison.OrdinalIgnoreCase))
                return true;
        return false;
    }

    private static string SafeLocalReturnUrl(string? returnUrl) =>
        !string.IsNullOrEmpty(returnUrl)
        && returnUrl.StartsWith('/')
        && !returnUrl.StartsWith("//")
        && Uri.IsWellFormedUriString(returnUrl, UriKind.Relative)
            ? returnUrl
            : "/";
}

public static class AuthenticatedIdentityFormsRedirectMiddlewareExtensions
{
    public static IApplicationBuilder UseAuthenticatedIdentityFormsRedirect(this IApplicationBuilder app)
        => app.UseMiddleware<AuthenticatedIdentityFormsRedirectMiddleware>();
}
