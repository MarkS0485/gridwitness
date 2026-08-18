using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json.Serialization;

namespace GridWitness.Portal.Services;

// ---- Wire DTOs for the survey/export surface (snake_case to match the FastAPI contract) ----

/// <summary>Non-file survey metadata forwarded with an upload.</summary>
public sealed class SurveyMeta
{
    public string Label { get; init; } = "";
    public string LocTier { get; init; } = "region";
    public string? Region { get; init; }
    public string? Postcode { get; init; }
    public string DeviceType { get; init; } = "unknown";
    public string? Notes { get; init; }
}

public sealed class SurveyRejectedDto
{
    [JsonPropertyName("filename")] public string? Filename { get; set; }
    [JsonPropertyName("reason")] public string? Reason { get; set; }
}

public sealed class SurveyAcceptedDto
{
    [JsonPropertyName("survey_id")] public string SurveyId { get; set; } = "";
    [JsonPropertyName("node_id")] public string NodeId { get; set; } = "";
    [JsonPropertyName("loc_ref")] public string? LocRef { get; set; }
    [JsonPropertyName("accepted")] public int Accepted { get; set; }
    [JsonPropertyName("rejected")] public List<SurveyRejectedDto> Rejected { get; set; } = new();
}

/// <summary>
/// Typed client for the ingest server's bulk surfaces — survey-file upload and account data export.
/// Separate from <see cref="IngestAdminClient"/> because these carry large bodies and need a much
/// longer timeout than the snappy admin calls; it is registered in Program.cs with the same private
/// <c>X-GW-Internal</c> credential and a multi-minute timeout.
/// </summary>
public sealed class IngestBulkClient
{
    private readonly HttpClient _http;
    private readonly ILogger<IngestBulkClient> _log;

    public IngestBulkClient(HttpClient http, ILogger<IngestBulkClient> log)
    {
        _http = http;
        _log = log;
    }

    /// <summary>Forward a batch of survey files (multipart) for a contributor. The server stashes them
    /// and returns immediately; the out-of-band worker parses them later.</summary>
    public async Task<SurveyAcceptedDto> UploadSurveyAsync(
        string contributorRef, SurveyMeta meta, IEnumerable<IFormFile> files, CancellationToken ct = default)
    {
        using var content = new MultipartFormDataContent();
        content.Add(new StringContent(contributorRef), "contributor_ref");
        content.Add(new StringContent(meta.Label), "label");
        content.Add(new StringContent(meta.LocTier), "loc_tier");
        if (!string.IsNullOrWhiteSpace(meta.Region)) content.Add(new StringContent(meta.Region), "region");
        if (!string.IsNullOrWhiteSpace(meta.Postcode)) content.Add(new StringContent(meta.Postcode), "postcode");
        content.Add(new StringContent(string.IsNullOrWhiteSpace(meta.DeviceType) ? "unknown" : meta.DeviceType), "device_type");
        if (!string.IsNullOrWhiteSpace(meta.Notes)) content.Add(new StringContent(meta.Notes), "notes");

        foreach (var f in files)
        {
            var part = new StreamContent(f.OpenReadStream());
            part.Headers.ContentType = new MediaTypeHeaderValue(
                string.IsNullOrWhiteSpace(f.ContentType) ? "application/octet-stream" : f.ContentType);
            content.Add(part, "files", f.FileName);
        }

        var resp = await _http.PostAsync("/v1/survey/upload", content, ct);
        resp.EnsureSuccessStatusCode();
        return await resp.Content.ReadFromJsonAsync<SurveyAcceptedDto>(ct)
               ?? throw new InvalidOperationException("Empty upload response from ingest server.");
    }

    /// <summary>Fetch the contributor's full data export as a zip. Buffered so the caller can stream it
    /// to the browser without holding the upstream connection open. Non-destructive.</summary>
    public async Task<byte[]> ExportAsync(string contributorRef, CancellationToken ct = default)
    {
        var url = $"/v1/account/export?contributor_ref={Uri.EscapeDataString(contributorRef)}";
        var resp = await _http.GetAsync(url, ct);
        resp.EnsureSuccessStatusCode();
        return await resp.Content.ReadAsByteArrayAsync(ct);
    }
}
