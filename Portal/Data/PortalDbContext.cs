using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Identity.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore;

namespace GridWitness.Portal.Data;

/// <summary>
/// Accounts only. The portal deliberately stores no nodes, no tokens and no measurement data — those
/// live in the Python ingest server, which remains the single source of truth. All this DbContext
/// holds is the ASP.NET Identity account tables: an email (the confirmable, contactable identity) and
/// the credential. That is the bare-minimum PII needed to prove ownership and honour GDPR rights;
/// every node is linked back to <c>IdentityUser.Id</c> (the contributor_ref) on the server side.
/// </summary>
public sealed class PortalDbContext : IdentityDbContext<IdentityUser>
{
    public PortalDbContext(DbContextOptions<PortalDbContext> options) : base(options)
    {
    }
}
