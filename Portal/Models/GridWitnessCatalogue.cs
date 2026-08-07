namespace GridWitness.Portal.Models;

/// <summary>A per-channel consent bundle, mirroring the HA plugin's "earn the ask" groups.</summary>
public sealed record ConsentGroup(
    string Key,
    string Title,
    string Sensitivity,          // "none" | "low" | "high"
    string Blurb,
    string[] Channels,
    bool DefaultOn = false);

/// <summary>A GB region a contributor can pick under REGION tier (no address shared).</summary>
public sealed record RegionOption(string Value, string Label);

/// <summary>
/// Static, hand-kept mirror of the server's channel/consent model and the GB region list. Kept in
/// sync with <c>server/gridwitness_server/models.py</c> (channels) and <c>privacy.py</c> (regions).
/// </summary>
public static class GridWitnessCatalogue
{
    public static readonly IReadOnlyList<ConsentGroup> ConsentGroups = new List<ConsentGroup>
    {
        new("frequency", "System frequency", "none",
            "The grid frequency (~50 Hz). Global, not tied to your address, and the backbone of the network. Recommended for everyone.",
            new[] { "frequency_hz" }, DefaultOn: true),
        new("voltage", "Voltage", "low",
            "RMS voltage. A property of your local feeder, not of you — low sensitivity, and it makes regional mapping far richer.",
            new[] { "voltage_v" }),
        new("current_power", "Current & power", "high",
            "Current, real power and power factor. These reveal household load and behaviour, so they are strictly opt-in.",
            new[] { "current_a", "power_w", "power_factor" }),
        new("weather", "Local weather", "low",
            "Temperature, humidity, wind, pressure, rainfall and irradiance from a co-located station. Helps explain demand and generation.",
            new[] { "temp", "rhum", "wspd", "wdir", "pres", "prcp", "solar_radiation_w_m2", "uv" }),
        new("phase_angle", "Phase angle (PMU)", "low",
            "Synchrophasor angle versus a UTC reference. Only GPS-synced PMU nodes can produce this — the fleet's timing anchors.",
            new[] { "phase_angle_deg" }),
    };

    public static readonly IReadOnlyList<RegionOption> Regions = new List<RegionOption>
    {
        new("NORTH_SCOTLAND", "North Scotland"),
        new("CENTRAL_SCOTLAND", "Central & Southern Scotland"),
        new("NORTH_EAST", "North East England"),
        new("NORTH_WEST", "North West England"),
        new("MERSEY", "Merseyside & North Wales"),
        new("YORKSHIRE", "Yorkshire"),
        new("MIDLANDS", "West Midlands"),
        new("EAST_MIDLANDS", "East Midlands"),
        new("EAST_ENGLAND", "East England"),
        new("LONDON", "London"),
        new("SOUTH_WALES", "South Wales"),
        new("SOUTH_WEST", "South West England"),
        new("SOUTHERN", "Southern England"),
        new("SOUTH_EAST", "South East England"),
    };

    /// <summary>Expand a set of selected group keys into the flat channel list the server expects.</summary>
    public static List<string> ChannelsForGroups(IEnumerable<string> groupKeys)
    {
        var keys = groupKeys.ToHashSet();
        return ConsentGroups
            .Where(g => keys.Contains(g.Key))
            .SelectMany(g => g.Channels)
            .Distinct()
            .ToList();
    }

    private static readonly Dictionary<string, string> ChannelLabels = new()
    {
        ["frequency_hz"] = "Frequency", ["voltage_v"] = "Voltage",
        ["current_a"] = "Current", ["power_w"] = "Power", ["power_factor"] = "Power factor",
        ["phase_angle_deg"] = "Phase angle",
        ["temp"] = "Temp", ["rhum"] = "Humidity", ["wspd"] = "Wind speed", ["wdir"] = "Wind dir",
        ["pres"] = "Pressure", ["prcp"] = "Rainfall", ["solar_radiation_w_m2"] = "Irradiance", ["uv"] = "UV",
    };

    public static string ChannelLabel(string channel) =>
        ChannelLabels.TryGetValue(channel, out var l) ? l : channel;
}
