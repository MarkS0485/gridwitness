using GridWitness.Portal.Models;
using GridWitness.Portal.Services;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;

namespace GridWitness.Portal.Controllers;

/// <summary>
/// The signed-in account area: list your nodes, issue new API keys, and manage or erase them.
///
/// GDPR gate: creating a key and contributing data do NOT require a confirmed email, but altering
/// consent or erasing data DO — a confirmed email is the proof of ownership we act on. The gate is
/// enforced here (server-side) on every mutating action, not just hidden in the UI.
/// </summary>
[Authorize]
public sealed class DashboardController : Controller
{
    private readonly IngestAdminClient _ingest;
    private readonly UserManager<IdentityUser> _users;
    private readonly ILogger<DashboardController> _log;

    // Public API base shown in the copy-paste snippets. Overridable for non-prod hosts.
    private readonly string _ingestPublicUrl;

    public DashboardController(
        IngestAdminClient ingest,
        UserManager<IdentityUser> users,
        IConfiguration config,
        ILogger<DashboardController> log)
    {
        _ingest = ingest;
        _users = users;
        _log = log;
        _ingestPublicUrl = config["Ingest:PublicUrl"] ?? "https://ingest.twinscrollgridbalancer.co.uk";
    }

    private string Ref => _users.GetUserId(User)!;

    // ---- Index: the account's nodes -------------------------------------------------------------

    public async Task<IActionResult> Index(CancellationToken ct)
    {
        var user = await _users.GetUserAsync(User);
        IReadOnlyList<NodeDto> nodes = Array.Empty<NodeDto>();
        string? error = null;
        var healthy = false;
        try
        {
            nodes = await _ingest.ListNodesAsync(Ref, ct);
            healthy = true;
        }
        catch (Exception ex)
        {
            _log.LogError(ex, "Failed to list nodes for {Ref}", Ref);
            error = "The ingest service could not be reached. Your keys are safe — please try again shortly.";
        }

        return View(new DashboardIndexVm
        {
            Nodes = nodes,
            EmailConfirmed = user?.EmailConfirmed ?? false,
            Email = user?.Email ?? "",
            IngestHealthy = healthy,
            Error = error,
        });
    }

    // ---- Create a new API key (node) ------------------------------------------------------------

    [HttpGet]
    public IActionResult Create() => View(new CreateNodeVm());

    [HttpPost]
    [ValidateAntiForgeryToken]
    public async Task<IActionResult> Create(CreateNodeVm vm, CancellationToken ct)
    {
        // Always keep frequency selected — it is the low-sensitivity backbone channel.
        if (!vm.Groups.Contains("frequency")) vm.Groups.Add("frequency");

        var channels = GridWitnessCatalogue.ChannelsForGroups(vm.Groups);
        if (channels.Count == 0) ModelState.AddModelError(nameof(vm.Groups), "Choose at least one data type to share.");
        if (vm.LocTier == "region" && string.IsNullOrWhiteSpace(vm.Region))
            ModelState.AddModelError(nameof(vm.Region), "Pick a region, or choose Anonymous.");
        if (vm.LocTier == "data_share" && string.IsNullOrWhiteSpace(vm.Postcode))
            ModelState.AddModelError(nameof(vm.Postcode), "Enter a postcode, or choose a less precise option.");

        if (!ModelState.IsValid) return View(vm);

        var req = new RegisterNodeRequest
        {
            Channels = channels,
            LocTier = vm.LocTier,
            Region = vm.LocTier == "region" ? vm.Region : null,
            Postcode = vm.LocTier == "data_share" ? vm.Postcode : null,
            DeviceType = vm.DeviceType.Trim(),
            ContributorRef = Ref,
        };

        try
        {
            var result = await _ingest.RegisterAsync(req, ct);
            // Render the token once, straight from the POST result — never persisted anywhere.
            return View("TokenIssued", new TokenIssuedVm
            {
                NodeId = result.NodeId,
                Token = result.Token,
                LocRef = result.LocRef,
                DeviceType = req.DeviceType,
                IngestBaseUrl = _ingestPublicUrl,
            });
        }
        catch (Exception ex)
        {
            _log.LogError(ex, "Register failed for {Ref}", Ref);
            ModelState.AddModelError(string.Empty, "The ingest service could not issue a key right now. Please try again shortly.");
            return View(vm);
        }
    }

    // ---- Manage a single node -------------------------------------------------------------------

    [HttpGet]
    public async Task<IActionResult> Node(string id, CancellationToken ct)
    {
        var user = await _users.GetUserAsync(User);
        NodeDto? node;
        try
        {
            node = await _ingest.GetNodeAsync(id, Ref, ct);
        }
        catch (Exception ex)
        {
            _log.LogError(ex, "Failed to load node {Id}", id);
            TempData["Error"] = "The ingest service could not be reached.";
            return RedirectToAction(nameof(Index));
        }

        if (node is null) return NotFound();

        return View(new ManageNodeVm
        {
            Node = node,
            EmailConfirmed = user?.EmailConfirmed ?? false,
            Groups = GroupsFromChannels(node.Channels),
            LocTier = node.LocTier,
        });
    }

    [HttpPost]
    [ValidateAntiForgeryToken]
    public async Task<IActionResult> UpdateNode(string id, ManageNodeVm vm, CancellationToken ct)
    {
        if (!await IsConfirmedAsync())
        {
            TempData["Error"] = "Confirm your email address before changing what a node shares.";
            return RedirectToAction(nameof(Node), new { id });
        }

        if (!vm.Groups.Contains("frequency")) vm.Groups.Add("frequency");
        var body = new ConsentUpdateDto
        {
            Channels = GridWitnessCatalogue.ChannelsForGroups(vm.Groups),
            LocTier = vm.LocTier,
            Region = vm.LocTier == "region" ? vm.Region : null,
            Postcode = vm.LocTier == "data_share" ? vm.Postcode : null,
        };

        try
        {
            await _ingest.UpdateConsentAsync(id, Ref, body, ct);
            TempData["Message"] = "Sharing settings updated.";
        }
        catch (Exception ex)
        {
            _log.LogError(ex, "Update failed for node {Id}", id);
            TempData["Error"] = "The change could not be saved. Please try again shortly.";
        }
        return RedirectToAction(nameof(Node), new { id });
    }

    [HttpPost]
    [ValidateAntiForgeryToken]
    public async Task<IActionResult> DeleteNode(string id, CancellationToken ct)
    {
        if (!await IsConfirmedAsync())
        {
            TempData["Error"] = "Confirm your email address before deleting data. This proves the account is yours.";
            return RedirectToAction(nameof(Node), new { id });
        }

        try
        {
            var ok = await _ingest.DeleteAsync(id, Ref, ct);
            TempData["Message"] = ok
                ? "Node erased. Its data will be dropped from the lake on the next acquisition cycle."
                : "That node was already gone.";
        }
        catch (Exception ex)
        {
            _log.LogError(ex, "Delete failed for node {Id}", id);
            TempData["Error"] = "The node could not be erased right now. Please try again shortly.";
            return RedirectToAction(nameof(Node), new { id });
        }
        return RedirectToAction(nameof(Index));
    }

    // ---- helpers --------------------------------------------------------------------------------

    private async Task<bool> IsConfirmedAsync()
    {
        var user = await _users.GetUserAsync(User);
        return user?.EmailConfirmed ?? false;
    }

    /// <summary>Reverse-map a node's flat channel list back to the consent-group checkboxes.</summary>
    private static List<string> GroupsFromChannels(IReadOnlyCollection<string> channels)
    {
        var set = channels.ToHashSet();
        return GridWitnessCatalogue.ConsentGroups
            .Where(g => g.Channels.Any(set.Contains))
            .Select(g => g.Key)
            .ToList();
    }
}
