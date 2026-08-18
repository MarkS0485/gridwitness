using System.Net;
using System.Net.Http.Json;
using System.Text.Json.Serialization;

namespace GridWitness.Portal.Services;

/// <summary>Where the Python ingest server lives and the shared internal credential to reach it.</summary>
public sealed class IngestOptions
{
    public string BaseUrl { get; set; } = "http://localhost:8000";
    public string InternalKey { get; set; } = "";
}

// ---- Wire DTOs. Property names match the FastAPI (snake_case) contract exactly. ----

public sealed class RegisterNodeRequest
{
    [JsonPropertyName("channels")] public List<string> Channels { get; set; } = new() { "frequency_hz" };
    [JsonPropertyName("loc_tier")] public string LocTier { get; set; } = "anon";
    [JsonPropertyName("region")] public string? Region { get; set; }
    [JsonPropertyName("postcode")] public string? Postcode { get; set; }
    [JsonPropertyName("device_type")] public string DeviceType { get; set; } = "unknown";
    [JsonPropertyName("producer")] public string Producer { get; set; } = "gridwitness-portal/1.0";
    [JsonPropertyName("contributor_ref")] public string? ContributorRef { get; set; }
}

public sealed class RegisterResultDto
{
    [JsonPropertyName("node_id")] public string NodeId { get; set; } = "";
    [JsonPropertyName("token")] public string Token { get; set; } = "";
    [JsonPropertyName("loc_ref")] public string? LocRef { get; set; }
    [JsonPropertyName("cell_id")] public string? CellId { get; set; }
}

public sealed class NodeDto
{
    [JsonPropertyName("node_id")] public string NodeId { get; set; } = "";
    [JsonPropertyName("device_type")] public string? DeviceType { get; set; }
    [JsonPropertyName("firmware")] public string? Firmware { get; set; }
    [JsonPropertyName("cadence_ms")] public int? CadenceMs { get; set; }
    [JsonPropertyName("loc_tier")] public string LocTier { get; set; } = "anon";
    [JsonPropertyName("loc_ref")] public string? LocRef { get; set; }
    [JsonPropertyName("cell_id")] public string? CellId { get; set; }
    [JsonPropertyName("channels")] public List<string> Channels { get; set; } = new();
    [JsonPropertyName("producer")] public string? Producer { get; set; }
    [JsonPropertyName("created_utc")] public string CreatedUtc { get; set; } = "";
}

public sealed class ConsentUpdateDto
{
    [JsonPropertyName("channels")] public List<string>? Channels { get; set; }
    [JsonPropertyName("loc_tier")] public string? LocTier { get; set; }
    [JsonPropertyName("region")] public string? Region { get; set; }
    [JsonPropertyName("postcode")] public string? Postcode { get; set; }
}

/// <summary>
/// Typed client for the Python ingest server's account-facing surface. It provisions node tokens on
/// behalf of a signed-in account (populating <c>contributor_ref</c>) and manages those nodes through
/// the internal admin API. The internal credential travels only over the private container network —
/// it is attached as a default request header in Program.cs, never exposed to the browser.
/// </summary>
public sealed class IngestAdminClient
{
    private readonly HttpClient _http;
    private readonly ILogger<IngestAdminClient> _log;

    public IngestAdminClient(HttpClient http, ILogger<IngestAdminClient> log)
    {
        _http = http;
        _log = log;
    }

    /// <summary>All live nodes owned by an account (contributor_ref = the Identity user id).</summary>
    public async Task<IReadOnlyList<NodeDto>> ListNodesAsync(string contributorRef, CancellationToken ct = default)
    {
        var url = $"/v1/admin/nodes?contributor_ref={Uri.EscapeDataString(contributorRef)}";
        var nodes = await _http.GetFromJsonAsync<List<NodeDto>>(url, ct);
        return nodes ?? new List<NodeDto>();
    }

    /// <summary>Fetch a single owned node, or null if it isn't found under this account.</summary>
    public async Task<NodeDto?> GetNodeAsync(string nodeId, string contributorRef, CancellationToken ct = default)
    {
        var nodes = await ListNodesAsync(contributorRef, ct);
        return nodes.FirstOrDefault(n => n.NodeId == nodeId);
    }

    /// <summary>Provision a new node/token for an account. The plaintext token is returned once.</summary>
    public async Task<RegisterResultDto> RegisterAsync(RegisterNodeRequest req, CancellationToken ct = default)
    {
        var resp = await _http.PostAsJsonAsync("/v1/register", req, ct);
        resp.EnsureSuccessStatusCode();
        var result = await resp.Content.ReadFromJsonAsync<RegisterResultDto>(ct);
        return result ?? throw new InvalidOperationException("Empty register response from ingest server.");
    }

    /// <summary>Alter consent / location for an owned node.</summary>
    public async Task UpdateConsentAsync(string nodeId, string contributorRef, ConsentUpdateDto body, CancellationToken ct = default)
    {
        var url = $"/v1/admin/node/{Uri.EscapeDataString(nodeId)}?contributor_ref={Uri.EscapeDataString(contributorRef)}";
        var resp = await _http.PatchAsJsonAsync(url, body, ct);
        resp.EnsureSuccessStatusCode();
    }

    /// <summary>GDPR erasure of an owned node. Returns false if it was already gone.</summary>
    public async Task<bool> DeleteAsync(string nodeId, string contributorRef, CancellationToken ct = default)
    {
        var url = $"/v1/admin/node/{Uri.EscapeDataString(nodeId)}?contributor_ref={Uri.EscapeDataString(contributorRef)}";
        var resp = await _http.DeleteAsync(url, ct);
        if (resp.StatusCode == HttpStatusCode.NotFound) return false;
        resp.EnsureSuccessStatusCode();
        return true;
    }

    /// <summary>Is the ingest server reachable and healthy? Never throws — for status badges.</summary>
    public async Task<bool> HealthyAsync(CancellationToken ct = default)
    {
        try
        {
            var resp = await _http.GetAsync("/v1/health", ct);
            return resp.IsSuccessStatusCode;
        }
        catch (Exception ex)
        {
            _log.LogWarning(ex, "Ingest health check failed.");
            return false;
        }
    }
}
