using GridWitness.Portal.Models;
using GridWitness.Portal.Services;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;

namespace GridWitness.Portal.Controllers;

/// <summary>
/// Contribute a power-quality survey: drag-and-drop up to 100 analyser export files, from which the
/// server keeps only frequency and voltage. Mirrors <see cref="DashboardController"/>: account-scoped
/// via <c>contributor_ref</c>, mutating posts carry the antiforgery token, and the actions that act on
/// already-contributed data (withdraw, export) are gated on a confirmed email — the proof of ownership.
///
/// It is the contributor's data: they own it, can take a copy at any time (Export), and can withdraw
/// any survey (Withdraw). Withdrawal removes the raw files and drops the readings from the research
/// lake on the next cycle; analysis already built while the data was live cannot be un-made.
/// </summary>
[Authorize]
public sealed class UploadController : Controller
{
    private const string SurveyProducer = "gridwitness-survey";
    private const int MaxFiles = 100;
    private static readonly HashSet<string> AllowedExtensions =
        new(StringComparer.OrdinalIgnoreCase) { ".csv", ".txt", ".tsv", ".pqd", ".pqdif" };

    private readonly IngestAdminClient _ingest;
    private readonly IngestBulkClient _bulk;
    private readonly UserManager<IdentityUser> _users;
    private readonly ILogger<UploadController> _log;

    public UploadController(
        IngestAdminClient ingest,
        IngestBulkClient bulk,
        UserManager<IdentityUser> users,
        ILogger<UploadController> log)
    {
        _ingest = ingest;
        _bulk = bulk;
        _users = users;
        _log = log;
    }

    private string Ref => _users.GetUserId(User)!;

    // ---- The upload form ------------------------------------------------------------------------

    [HttpGet]
    public IActionResult Index() => View(new SurveyUploadVm());

    [HttpPost]
    [ValidateAntiForgeryToken]
    [RequestSizeLimit(600_000_000)]  // ~600 MB batch ceiling; see FormOptions in Program.cs
    public async Task<IActionResult> Index(SurveyUploadVm vm, List<IFormFile> files, CancellationToken ct)
    {
        // File-level validation (the VM can't express the file collection's rules).
        files ??= new List<IFormFile>();
        if (files.Count == 0)
            ModelState.AddModelError(string.Empty, "Add at least one survey file.");
        if (files.Count > MaxFiles)
            ModelState.AddModelError(string.Empty, $"Up to {MaxFiles} files at a time — you added {files.Count}.");
        foreach (var f in files)
        {
            var ext = Path.GetExtension(f.FileName);
            if (!AllowedExtensions.Contains(ext))
                ModelState.AddModelError(string.Empty, $"'{f.FileName}' isn't a supported type (.csv, .txt, .pqd, .pqdif).");
        }

        // Surveys must carry a location — a voltage trace is only useful pinned to a place.
        if (vm.LocTier == "region" && string.IsNullOrWhiteSpace(vm.Region))
            ModelState.AddModelError(nameof(vm.Region), "Pick a region.");
        if (vm.LocTier == "data_share" && string.IsNullOrWhiteSpace(vm.Postcode))
            ModelState.AddModelError(nameof(vm.Postcode), "Enter a postcode, or choose Region.");

        // Consent is a bool, so it's enforced here rather than with a client-side Range attribute.
        if (!vm.Consent)
            ModelState.AddModelError(nameof(vm.Consent), "Please confirm you're happy to contribute this data.");

        if (!ModelState.IsValid) return View(vm);

        var meta = new SurveyMeta
        {
            Label = vm.Label.Trim(),
            LocTier = vm.LocTier,
            Region = vm.LocTier == "region" ? vm.Region : null,
            Postcode = vm.LocTier == "data_share" ? vm.Postcode : null,
            DeviceType = string.IsNullOrWhiteSpace(vm.DeviceType) ? "unknown" : vm.DeviceType!.Trim(),
            Notes = vm.Notes,
        };

        try
        {
            var result = await _bulk.UploadSurveyAsync(Ref, meta, files, ct);
            return View("Received", new SurveyReceivedVm
            {
                NodeId = result.NodeId,
                Accepted = result.Accepted,
                Rejected = result.Rejected,
            });
        }
        catch (Exception ex)
        {
            _log.LogError(ex, "Survey upload failed for {Ref}", Ref);
            ModelState.AddModelError(string.Empty, "The upload could not be received right now. Please try again shortly.");
            return View(vm);
        }
    }

    // ---- The account's surveys ------------------------------------------------------------------

    [HttpGet]
    public async Task<IActionResult> Surveys(CancellationToken ct)
    {
        var user = await _users.GetUserAsync(User);
        IReadOnlyList<NodeDto> surveys = Array.Empty<NodeDto>();
        string? error = null;
        var healthy = false;
        try
        {
            var nodes = await _ingest.ListNodesAsync(Ref, ct);
            surveys = nodes.Where(n => n.Producer == SurveyProducer).ToList();
            healthy = true;
        }
        catch (Exception ex)
        {
            _log.LogError(ex, "Failed to list surveys for {Ref}", Ref);
            error = "The ingest service could not be reached. Your data is safe — please try again shortly.";
        }

        return View(new SurveyListVm
        {
            Surveys = surveys,
            EmailConfirmed = user?.EmailConfirmed ?? false,
            IngestHealthy = healthy,
            Error = error,
        });
    }

    // ---- Withdraw one survey (erasure) ----------------------------------------------------------

    [HttpPost]
    [ValidateAntiForgeryToken]
    public async Task<IActionResult> Withdraw(string id, CancellationToken ct)
    {
        if (!await IsConfirmedAsync())
        {
            TempData["Error"] = "Confirm your email address before withdrawing data. This proves the account is yours.";
            return RedirectToAction(nameof(Surveys));
        }

        try
        {
            var ok = await _ingest.DeleteAsync(id, Ref, ct);
            TempData["Message"] = ok
                ? "Survey withdrawn. Your files are removed and the readings drop from the research lake on the next cycle."
                : "That survey was already gone.";
        }
        catch (Exception ex)
        {
            _log.LogError(ex, "Withdraw failed for survey {Id}", id);
            TempData["Error"] = "The survey could not be withdrawn right now. Please try again shortly.";
        }
        return RedirectToAction(nameof(Surveys));
    }

    // ---- Export: take your data with you --------------------------------------------------------

    [HttpGet]
    public async Task<IActionResult> Export(CancellationToken ct)
    {
        if (!await IsConfirmedAsync())
        {
            TempData["Error"] = "Confirm your email address before exporting data. This proves the account is yours.";
            return RedirectToAction(nameof(Surveys));
        }

        try
        {
            var zip = await _bulk.ExportAsync(Ref, ct);
            return File(zip, "application/zip", "my-gridwitness-data.zip");
        }
        catch (Exception ex)
        {
            _log.LogError(ex, "Export failed for {Ref}", Ref);
            TempData["Error"] = "Your export could not be built right now. Please try again shortly.";
            return RedirectToAction(nameof(Surveys));
        }
    }

    // ---- helpers --------------------------------------------------------------------------------

    private async Task<bool> IsConfirmedAsync()
    {
        var user = await _users.GetUserAsync(User);
        return user?.EmailConfirmed ?? false;
    }
}
