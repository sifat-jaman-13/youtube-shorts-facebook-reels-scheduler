using System.Net;
using System.Text;
using System.Text.Json;
using ScarClipScheduler.Wpf;

var handler = new RecordingHandler();
using (var api = new ApiClient(new Uri("http://127.0.0.1:1/"), "contract-test-token", handler))
{
    using var response = await api.PostConfirmedAsync(
        "api/schedule",
        new Dictionary<string, object?>
        {
            ["confirmed"] = true,
            ["rights_confirmed"] = true
        });
    if (!response.RootElement.GetProperty("started").GetBoolean())
        throw new InvalidOperationException("The fake scheduling endpoint did not return started=true.");
}

if (!string.Equals(handler.ConfirmationHeader, "true", StringComparison.OrdinalIgnoreCase))
    throw new InvalidOperationException("The native client did not send X-Scar-User-Confirmed: true.");

using (var body = JsonDocument.Parse(handler.Body))
{
    if (!body.RootElement.TryGetProperty("confirmed", out var confirmed) || confirmed.ValueKind != JsonValueKind.True)
        throw new InvalidOperationException("The native client did not serialize confirmed=true in the JSON body.");
}

var ordinaryHandler = new RecordingHandler();
using (var api = new ApiClient(new Uri("http://127.0.0.1:1/"), "contract-test-token", ordinaryHandler))
{
    using var response = await api.PostAsync("api/settings", new Dictionary<string, object?> { ["safe"] = true });
}
if (ordinaryHandler.ConfirmationHeader is not null)
    throw new InvalidOperationException("A normal settings request incorrectly carried the scheduling confirmation header.");

Console.WriteLine("PASS: WPF API client sends explicit confirmation header and JSON flag only for confirmed scheduling.");
Console.WriteLine("PASS: Ordinary API requests do not carry the scheduling confirmation header.");

// Start the production Python worker in an isolated data directory and
// exercise its authenticated HTTP API without touching any connected accounts.
var isolatedData = Path.Combine(Path.GetTempPath(), "ScarClipScheduler.ApiContractTests-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(isolatedData);
Environment.SetEnvironmentVariable("SCARCLIPSCHEDULER_DATA_DIR", isolatedData);
try
{
    await using var backend = await BackendHost.StartAsync();
    var state = await backend.Api.GetStateAsync();
    if (state.Version != "2.0.14")
        throw new InvalidOperationException($"Expected worker version 2.0.14, received {state.Version}.");

    try
    {
        using var rejected = await backend.Api.PostAsync("api/schedule", new Dictionary<string, object?>());
        throw new InvalidOperationException("The real worker accepted an unconfirmed scheduling request.");
    }
    catch (InvalidOperationException ex) when (ex.Message.Contains("explicit desktop user confirmation", StringComparison.Ordinal))
    {
        Console.WriteLine("PASS: production BackendHost starts the matching 2.0.14 worker and reads its state.");
        Console.WriteLine("PASS: production worker rejects scheduling without explicit confirmation.");
    }
}
finally
{
    try { Directory.Delete(isolatedData, recursive: true); } catch { }
}

sealed class RecordingHandler : HttpMessageHandler
{
    public string? ConfirmationHeader { get; private set; }
    public string Body { get; private set; } = "{}";

    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken)
    {
        ConfirmationHeader = request.Headers.TryGetValues("X-Scar-User-Confirmed", out var values)
            ? string.Join(",", values)
            : null;
        Body = request.Content is null
            ? "{}"
            : await request.Content.ReadAsStringAsync(cancellationToken);
        return new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent("{\"started\":true}", Encoding.UTF8, "application/json")
        };
    }
}
