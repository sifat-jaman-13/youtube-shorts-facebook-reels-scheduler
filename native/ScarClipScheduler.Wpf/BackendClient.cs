using System.Net.Http.Json;
using System.IO;
using System.Diagnostics;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace ScarClipScheduler.Wpf;

public sealed class BackendHost : IAsyncDisposable
{
    private readonly Process _process;
    public ApiClient Api { get; }
    public int Port { get; }

    private BackendHost(Process process, string token, int port)
    {
        _process = process;
        Port = port;
        Api = new ApiClient(new Uri($"http://127.0.0.1:{port}/"), token);
    }

    public static async Task<BackendHost> StartAsync(CancellationToken cancellationToken = default)
    {
        var baseDir = AppContext.BaseDirectory;
        var backendScript = Path.Combine(baseDir, "backend", "backend_service.py");
        if (!File.Exists(backendScript))
            throw new FileNotFoundException("The background publishing worker was not found.", backendScript);

        var python = Environment.GetEnvironmentVariable("SCARCLIP_PYTHON");
        if (string.IsNullOrWhiteSpace(python))
        {
            var localVenv = Path.Combine(baseDir, ".venv", "Scripts", "python.exe");
            var installedVenv = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Programs", "ScarClipScheduler", ".venv", "Scripts", "python.exe");
            python = File.Exists(localVenv) ? localVenv :
                     File.Exists(installedVenv) ? installedVenv : "python.exe";
        }

        var token = Convert.ToHexString(RandomNumberGenerator.GetBytes(32));
        var startInfo = new ProcessStartInfo
        {
            FileName = python,
            WorkingDirectory = Path.GetDirectoryName(backendScript)!,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8
        };
        startInfo.ArgumentList.Add(backendScript);
        startInfo.ArgumentList.Add("--port");
        startInfo.ArgumentList.Add("0");
        startInfo.ArgumentList.Add("--token");
        startInfo.ArgumentList.Add(token);

        var process = new Process { StartInfo = startInfo, EnableRaisingEvents = true };
        if (!process.Start())
            throw new InvalidOperationException("Could not start the publishing worker.");

        _ = PumpStandardErrorAsync(process, baseDir);
        try
        {
            var readyLineTask = process.StandardOutput.ReadLineAsync(cancellationToken).AsTask();
            var timeoutTask = Task.Delay(TimeSpan.FromSeconds(35), cancellationToken);
            var finishedTask = process.WaitForExitAsync(cancellationToken);
            var completed = await Task.WhenAny(readyLineTask, timeoutTask, finishedTask);
            if (completed == timeoutTask)
                throw new TimeoutException("The publishing worker did not start within 35 seconds.");
            if (completed == finishedTask)
                throw new InvalidOperationException($"The publishing worker exited with code {process.ExitCode}.");
            var line = await readyLineTask;
            if (string.IsNullOrWhiteSpace(line))
                throw new InvalidOperationException("The publishing worker closed its startup channel.");
            using var document = JsonDocument.Parse(line);
            var root = document.RootElement;
            if (!root.TryGetProperty("ready", out var ready) || !ready.GetBoolean())
                throw new InvalidOperationException("The publishing worker returned an invalid startup response.");
            var port = root.GetProperty("port").GetInt32();
            return new BackendHost(process, token, port);
        }
        catch
        {
            try { if (!process.HasExited) process.Kill(entireProcessTree: true); } catch { }
            process.Dispose();
            throw;
        }
    }

    private static async Task PumpStandardErrorAsync(Process process, string baseDir)
    {
        try
        {
            var logDir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "ScarClipScheduler");
            Directory.CreateDirectory(logDir);
            var logPath = Path.Combine(logDir, "native-backend-stderr.log");
            while (!process.HasExited)
            {
                var line = await process.StandardError.ReadLineAsync();
                if (line is null) break;
                await File.AppendAllTextAsync(logPath, line + Environment.NewLine);
            }
        }
        catch
        {
            // The main app surfaces worker startup and request errors separately.
        }
    }

    public async ValueTask DisposeAsync()
    {
        Api.Dispose();
        try
        {
            if (!_process.HasExited)
                _process.Kill(entireProcessTree: true);
        }
        catch { }
        await Task.Run(() =>
        {
            try { _process.WaitForExit(2500); } catch { }
            _process.Dispose();
        });
    }
}

public sealed class ApiClient : IDisposable
{
    private readonly HttpClient _http;
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true
    };

    public ApiClient(Uri baseUri, string token)
    {
        _http = new HttpClient
        {
            BaseAddress = baseUri,
            Timeout = TimeSpan.FromSeconds(35)
        };
        _http.DefaultRequestHeaders.Add("X-Scar-Token", token);
    }

    public async Task<NativeState> GetStateAsync(CancellationToken cancellationToken = default)
    {
        using var response = await _http.GetAsync("api/state", cancellationToken);
        await EnsureSuccess(response, cancellationToken);
        var value = await response.Content.ReadFromJsonAsync<NativeState>(JsonOptions, cancellationToken);
        return value ?? throw new InvalidOperationException("The worker returned an empty state response.");
    }

    public async Task<List<NativeEvent>> GetEventsAsync(long after, CancellationToken cancellationToken = default)
    {
        using var response = await _http.GetAsync($"api/events?after={after}", cancellationToken);
        await EnsureSuccess(response, cancellationToken);
        var value = await response.Content.ReadFromJsonAsync<EventEnvelope>(JsonOptions, cancellationToken);
        return value?.Events ?? [];
    }

    public async Task<JsonDocument> PostAsync(string route, object body, CancellationToken cancellationToken = default)
    {
        using var response = await _http.PostAsJsonAsync(route, body, JsonOptions, cancellationToken);
        await EnsureSuccess(response, cancellationToken);
        return await JsonDocument.ParseAsync(
            await response.Content.ReadAsStreamAsync(cancellationToken), cancellationToken: cancellationToken);
    }

    private static async Task EnsureSuccess(HttpResponseMessage response, CancellationToken cancellationToken)
    {
        if (response.IsSuccessStatusCode)
            return;

        var raw = await response.Content.ReadAsStringAsync(cancellationToken);
        try
        {
            using var doc = JsonDocument.Parse(raw);
            var message = doc.RootElement.TryGetProperty("error", out var error)
                ? error.GetString()
                : raw;
            throw new InvalidOperationException(message ?? "The publishing worker returned an error.");
        }
        catch (JsonException)
        {
            throw new InvalidOperationException(
                string.IsNullOrWhiteSpace(raw) ? $"Worker request failed ({(int)response.StatusCode})." : raw);
        }
    }

    public void Dispose() => _http.Dispose();

    private sealed class EventEnvelope
    {
        public List<NativeEvent> Events { get; set; } = [];
    }
}
