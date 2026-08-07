using System.ComponentModel.DataAnnotations;
using GridWitness.Portal.Services;

namespace GridWitness.Portal.Models;

/// <summary>The dashboard landing page: an account's nodes plus the guards that shape the UI.</summary>
public sealed class DashboardIndexVm
{
    public IReadOnlyList<NodeDto> Nodes { get; init; } = Array.Empty<NodeDto>();
    public bool EmailConfirmed { get; init; }
    public string Email { get; init; } = "";
    public bool IngestHealthy { get; init; }
    public string? Error { get; init; }
}

/// <summary>The "create an API key" form.</summary>
public sealed class CreateNodeVm
{
    [Display(Name = "Name / device")]
    [Required, StringLength(60)]
    public string DeviceType { get; set; } = "";

    /// <summary>Selected consent-group keys (see <see cref="GridWitnessCatalogue.ConsentGroups"/>).</summary>
    public List<string> Groups { get; set; } = new() { "frequency" };

    [Display(Name = "Location sharing")]
    public string LocTier { get; set; } = "anon";   // anon | region | data_share

    public string? Region { get; set; }

    [Display(Name = "Postcode")]
    public string? Postcode { get; set; }
}

/// <summary>Shown exactly once, immediately after a key is issued — the token is never stored.</summary>
public sealed class TokenIssuedVm
{
    public string NodeId { get; init; } = "";
    public string Token { get; init; } = "";
    public string? LocRef { get; init; }
    public string DeviceType { get; init; } = "";
    public string IngestBaseUrl { get; init; } = "https://ingest.twinscrollgridbalancer.co.uk";
}

/// <summary>Manage a single node: alter consent/location or erase it (both gated on a confirmed email).</summary>
public sealed class ManageNodeVm
{
    public NodeDto Node { get; init; } = new();
    public bool EmailConfirmed { get; init; }
    public List<string> Groups { get; set; } = new();
    public string LocTier { get; set; } = "anon";
    public string? Region { get; set; }
    public string? Postcode { get; set; }
}
