using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace ScarClipScheduler.Wpf;

public sealed class NativeState
{
    [JsonPropertyName("version")] public string Version { get; set; } = "";
    [JsonPropertyName("folder")] public string Folder { get; set; } = "";
    [JsonPropertyName("start_at")] public string StartAt { get; set; } = "";
    [JsonPropertyName("interval_minutes")] public int IntervalMinutes { get; set; } = 5;
    [JsonPropertyName("youtube_enabled")] public bool YoutubeEnabled { get; set; }
    [JsonPropertyName("facebook_enabled")] public bool FacebookEnabled { get; set; }
    [JsonPropertyName("youtube_ai")] public bool YoutubeAi { get; set; }
    [JsonPropertyName("facebook_ai")] public bool FacebookAi { get; set; }
    [JsonPropertyName("made_for_kids")] public bool MadeForKids { get; set; }
    [JsonPropertyName("category_id")] public string CategoryId { get; set; } = "20";
    [JsonPropertyName("client_secrets")] public string ClientSecrets { get; set; } = "";
    [JsonPropertyName("meta_app_id")] public string MetaAppId { get; set; } = "";
    [JsonPropertyName("business_id")] public string BusinessId { get; set; } = "";
    [JsonPropertyName("youtube_channel")] public string YoutubeChannel { get; set; } = "";
    [JsonPropertyName("youtube_channel_id")] public string YoutubeChannelId { get; set; } = "";
    [JsonPropertyName("youtube_connected")] public bool YoutubeConnected { get; set; }
    [JsonPropertyName("facebook_connected")] public bool FacebookConnected { get; set; }
    [JsonPropertyName("youtube_connecting")] public bool YoutubeConnecting { get; set; }
    [JsonPropertyName("facebook_connecting")] public bool FacebookConnecting { get; set; }
    [JsonPropertyName("facebook_pages")] public List<PageDto> FacebookPages { get; set; } = [];
    [JsonPropertyName("rows")] public List<ClipDto> Rows { get; set; } = [];
    [JsonPropertyName("scheduled_rows")] public List<ClipDto> ScheduledRows { get; set; } = [];
    [JsonPropertyName("counts")] public Dictionary<string, int> Counts { get; set; } = [];
    [JsonPropertyName("total")] public int Total { get; set; }
    [JsonPropertyName("detected_total")] public int DetectedTotal { get; set; }
    [JsonPropertyName("scheduled_total")] public int ScheduledTotal { get; set; }
    [JsonPropertyName("busy")] public bool Busy { get; set; }
    [JsonPropertyName("queue_running")] public bool QueueRunning { get; set; }
    [JsonPropertyName("scan_running")] public bool ScanRunning { get; set; }
    [JsonPropertyName("verification_running")] public bool VerificationRunning { get; set; }
}

public sealed class ClipDto
{
    [JsonPropertyName("path")] public string Path { get; set; } = "";
    [JsonPropertyName("file")] public string File { get; set; } = "";
    [JsonPropertyName("title")] public string Title { get; set; } = "";
    [JsonPropertyName("description")] public string Description { get; set; } = "";
    [JsonPropertyName("duration")] public double? Duration { get; set; }
    [JsonPropertyName("width")] public int? Width { get; set; }
    [JsonPropertyName("height")] public int? Height { get; set; }
    [JsonPropertyName("fb_ok")] public int? FacebookFormatOk { get; set; }
    [JsonPropertyName("queue_status")] public string QueueStatus { get; set; } = "Pending";
    [JsonPropertyName("yt_status")] public string YoutubeStatus { get; set; } = "Pending";
    [JsonPropertyName("fb_status")] public string FacebookStatus { get; set; } = "Pending";
    [JsonPropertyName("publish_at")] public string PublishAt { get; set; } = "";
    [JsonPropertyName("scheduled_times")] public string ScheduledTimes { get; set; } = "";
    [JsonPropertyName("storage_state")] public string StorageState { get; set; } = "source";
    [JsonPropertyName("yt_video_id")] public string YoutubeVideoId { get; set; } = "";
    [JsonPropertyName("facebook_pages")] public List<PageJobDto> FacebookPageJobs { get; set; } = [];
}

public sealed class PageJobDto
{
    [JsonPropertyName("page_id")] public string PageId { get; set; } = "";
    [JsonPropertyName("page_name")] public string PageName { get; set; } = "";
    [JsonPropertyName("status")] public string Status { get; set; } = "Pending";
    [JsonPropertyName("publish_at")] public string PublishAt { get; set; } = "";
    [JsonPropertyName("error")] public string Error { get; set; } = "";
}

public sealed class PageDto : ObservableObject
{
    private bool _selected;
    [JsonPropertyName("id")] public string Id { get; set; } = "";
    [JsonPropertyName("name")] public string Name { get; set; } = "";
    [JsonPropertyName("selected")]
    public bool Selected
    {
        get => _selected;
        set => Set(ref _selected, value);
    }
}

public sealed class NativeEvent
{
    [JsonPropertyName("id")] public long Id { get; set; }
    [JsonPropertyName("type")] public string Type { get; set; } = "";
    [JsonPropertyName("data")] public JsonElement Data { get; set; }
}

public sealed class ClipRow : ObservableObject
{
    public string Path { get; private set; } = "";
    private int _number;
    public int Number { get => _number; set => Set(ref _number, value); }
    private string _file = "";
    private string _title = "";
    private string _description = "";
    private string _fullDescription = "";
    private string _queueStatus = "Pending";
    private string _youtubeStatus = "Pending";
    private string _facebookStatus = "Pending";
    private string _publishAt = "";
    private string _scheduledTimes = "";
    private double? _duration;

    public string File { get => _file; private set => Set(ref _file, value); }
    public string Title { get => _title; private set => Set(ref _title, value); }
    public string DescriptionPreview { get => _description; private set => Set(ref _description, value); }
    public string Description { get => _fullDescription; private set => Set(ref _fullDescription, value); }
    public string QueueStatus { get => _queueStatus; private set => Set(ref _queueStatus, value); }
    public string YoutubeStatus { get => _youtubeStatus; private set => Set(ref _youtubeStatus, value); }
    public string FacebookStatus { get => _facebookStatus; private set => Set(ref _facebookStatus, value); }
    public string PublishAtText { get => _publishAt; private set => Set(ref _publishAt, value); }
    public string ScheduledTimes { get => _scheduledTimes; private set => Set(ref _scheduledTimes, value); }
    public double? Duration { get => _duration; private set => Set(ref _duration, value); }
    public string DurationText => Duration.HasValue ? $"{Duration.Value:0.0}s" : "—";

    public void Update(ClipDto row, int number)
    {
        Path = row.Path;
        Number = number;
        File = row.File;
        Title = row.Title;
        Description = row.Description;
        var compact = string.Join(" ", (row.Description ?? "").Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));
        DescriptionPreview = compact.Length > 150 ? compact[..147] + "..." : compact;
        QueueStatus = row.QueueStatus;
        YoutubeStatus = row.YoutubeStatus;
        FacebookStatus = row.FacebookStatus;
        Duration = row.Duration;
        OnPropertyChanged(nameof(DurationText));
        PublishAtText = FormatLocal(row.PublishAt);
        ScheduledTimes = row.ScheduledTimes;
    }

    private static string FormatLocal(string value)
    {
        if (DateTimeOffset.TryParse(value, out var parsed))
            return parsed.ToLocalTime().ToString("yyyy-MM-dd HH:mm");
        return "";
    }
}

public abstract class ObservableObject : INotifyPropertyChanged
{
    public event PropertyChangedEventHandler? PropertyChanged;

    protected bool Set<T>(ref T field, T value, [CallerMemberName] string? propertyName = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value))
            return false;
        field = value;
        OnPropertyChanged(propertyName);
        return true;
    }

    protected void OnPropertyChanged([CallerMemberName] string? propertyName = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
}
