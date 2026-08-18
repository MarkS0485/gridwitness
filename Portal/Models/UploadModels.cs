using System.ComponentModel.DataAnnotations;
using GridWitness.Portal.Services;

namespace GridWitness.Portal.Models;

/// <summary>
/// The "contribute a survey" form. Files are posted alongside as an <c>IFormFileCollection</c>, not on
/// the model. A survey is one monitoring session an electrician uploads; we keep only frequency and
/// voltage from the files. Location is required (region tier by default) because a voltage trace is
/// only useful pinned to a place — but a postcode never leaves the server, only a coarse derived area.
/// </summary>
public sealed class SurveyUploadVm
{
    [Display(Name = "Survey name")]
    [Required(ErrorMessage = "Give this survey a name so you can find it later."), StringLength(80)]
    public string Label { get; set; } = "";

    [Display(Name = "Analyser / device")]
    [StringLength(60)]
    public string? DeviceType { get; set; }

    [Display(Name = "Location sharing")]
    public string LocTier { get; set; } = "region";   // region | data_share (anon not offered for surveys)

    public string? Region { get; set; }

    [Display(Name = "Postcode")]
    public string? Postcode { get; set; }

    [Display(Name = "Notes (optional)")]
    [StringLength(500)]
    public string? Notes { get; set; }

    /// <summary>Must be true to submit — validated server-side (a bool can't carry a client Range rule).</summary>
    public bool Consent { get; set; }
}

/// <summary>Shown after a successful upload: what was queued, and what (if anything) was skipped.</summary>
public sealed class SurveyReceivedVm
{
    public string NodeId { get; init; } = "";
    public int Accepted { get; init; }
    public IReadOnlyList<SurveyRejectedDto> Rejected { get; init; } = Array.Empty<SurveyRejectedDto>();
}

/// <summary>The account's uploaded surveys, plus the confirmed-email guard that gates withdraw/export.</summary>
public sealed class SurveyListVm
{
    public IReadOnlyList<NodeDto> Surveys { get; init; } = Array.Empty<NodeDto>();
    public bool EmailConfirmed { get; init; }
    public bool IngestHealthy { get; init; }
    public string? Error { get; init; }
}
