using System.IO;
using Microsoft.Win32;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using System.Windows.Media.Imaging;
using System.Diagnostics;
using System.Windows.Documents;
using System.Windows.Navigation;

namespace ScarClipScheduler.Wpf;

public partial class MainWindow : Window
{
    public ObservableCollection<ClipRow> Clips { get; } = [];
    public ObservableCollection<PageDto> Pages { get; } = [];

    private BackendHost? _backend;
    private ApiClient? _api;
    private NativeState? _state;
    private readonly Dictionary<string, ClipRow> _rowsByPath = new(StringComparer.OrdinalIgnoreCase);
    private readonly DispatcherTimer _eventTimer;
    private readonly SemaphoreSlim _refreshLock = new(1, 1);
    private readonly SemaphoreSlim _eventLock = new(1, 1);
    private long _lastEventId;
    private bool _allowClose;
    private bool _initialStateApplied;
    private bool _applyingScheduleInputs;
    private bool _startTimeConfirmed;
    private DateTime? _confirmedStartAt;
    private int _confirmedInterval;
    private bool _shutdownInProgress;
    private bool _showAllAccepted;
    private string? _selectedMetadataPath;

    public MainWindow()
    {
        InitializeComponent();
        var appIcon = Path.Combine(AppContext.BaseDirectory, "backend", "assets", "scarclipscheduler.ico");
        if (File.Exists(appIcon))
            Icon = BitmapFrame.Create(new Uri(appIcon, UriKind.Absolute));
        Title = "ScarClipScheduler 2.0.15";
        DataContext = this;
        ClipGrid.ItemsSource = Clips;
        StartDate.DisplayDateStart = DateTime.Today;
        StartDate.SelectedDate = DateTime.Today;
        SetDefaultStartTime();

        _eventTimer = new DispatcherTimer
        {
            Interval = TimeSpan.FromMilliseconds(500)
        };
        _eventTimer.Tick += EventTimer_Tick;
    }

    private async void Window_Loaded(object sender, RoutedEventArgs e)
    {
        // Keep the complete native window inside the usable desktop area.
        // The original fixed 1560x960 size clipped controls on smaller displays.
        var workArea = SystemParameters.WorkArea;
        Width = Math.Min(Width, Math.Max(900, workArea.Width - 32));
        Height = Math.Min(Height, Math.Max(650, workArea.Height - 32));
        MinWidth = Math.Min(MinWidth, Width);
        MinHeight = Math.Min(MinHeight, Height);
        WindowStartupLocation = WindowStartupLocation.CenterScreen;

        FooterStatus.Text = "Starting native interface and background publishing service...";
        ConnectionSummary.Text = "Starting publishing worker...";
        try
        {
            _backend = await BackendHost.StartAsync();
            _api = _backend.Api;
            await RefreshStateAsync();
            _eventTimer.Start();
            FooterStatus.Text = $"Connected to background worker on local port {_backend.Port}.";
            AddActivity($"ScarClipScheduler native UI connected. Worker version {_state?.Version ?? "unknown"}.");
        }
        catch (Exception ex)
        {
            FooterStatus.Text = "Publishing worker could not start.";
            ConnectionSummary.Text = "Worker unavailable";
            AddActivity($"ERROR: {ex.Message}");
            MessageBox.Show(this,
                "ScarClipScheduler could not start its background publishing service.\n\n" + ex.Message,
                "Publishing service unavailable", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private async void EventTimer_Tick(object? sender, EventArgs e)
    {
        if (_api is null || !_eventLock.Wait(0))
            return;
        try
        {
            var events = await _api.GetEventsAsync(_lastEventId);
            var stateChanged = false;
            foreach (var item in events)
            {
                _lastEventId = Math.Max(_lastEventId, item.Id);
                switch (item.Type)
                {
                    case "log":
                        AddActivity(GetString(item.Data, "message"));
                        break;
                    case "state_changed":
                        stateChanged = true;
                        break;
                    case "operation_error":
                        var error = GetString(item.Data, "message");
                        AddActivity("ERROR: " + error);
                        FooterStatus.Text = error;
                        break;
                    case "dialog":
                        ShowBackendDialog(item.Data);
                        break;
                    case "confirmation":
                        // The native UI confirms destructive/publishing actions before dispatch.
                        break;
                }
            }
            if (stateChanged)
                await RefreshStateAsync();
        }
        catch (Exception ex)
        {
            FooterStatus.Text = $"Worker connection issue: {ex.Message}";
        }
        finally
        {
            _eventLock.Release();
        }
    }

    private async Task RefreshStateAsync()
    {
        if (_api is null || !await _refreshLock.WaitAsync(0))
            return;
        try
        {
            var state = await _api.GetStateAsync();
            _state = state;
            ApplyState(state);
        }
        finally
        {
            _refreshLock.Release();
        }
    }

    private void ApplyState(NativeState state)
    {
        if (!_initialStateApplied)
        {
            FolderBox.Text = state.Folder;
            ClientSecretsBox.Text = state.ClientSecrets;
            MetaAppIdBox.Text = state.MetaAppId;
            BusinessIdBox.Text = state.BusinessId;
            ApplyScheduleInputs(state);
            _initialStateApplied = true;
        }
        else
        {
            SetTextWhenNotFocused(FolderBox, state.Folder);
            SetTextWhenNotFocused(ClientSecretsBox, state.ClientSecrets);
        }

        YoutubeCheck.IsChecked = state.YoutubeEnabled;
        FacebookCheck.IsChecked = state.FacebookEnabled;
        YoutubeAiCheck.IsChecked = state.YoutubeAi;
        FacebookAiCheck.IsChecked = state.FacebookAi;
        MadeForKidsCheck.IsChecked = state.MadeForKids;
        RightsCheck.IsChecked = false;

        var category = CategoryBox.Items.OfType<ComboBoxItem>()
            .FirstOrDefault(x => string.Equals(x.Tag?.ToString(), state.CategoryId, StringComparison.Ordinal));
        if (category is not null)
            CategoryBox.SelectedItem = category;

        YoutubeStatus.Text = state.YoutubeConnecting
            ? "RECONNECTING  |  Complete Google authorization in your browser..."
            : state.YoutubeConnected
                ? $"CONNECTED  |  YouTube channel: {(string.IsNullOrWhiteSpace(state.YoutubeChannel) ? "Account authorization saved" : state.YoutubeChannel)}"
                : "NOT CONNECTED  |  Choose your Google OAuth Desktop client JSON, then connect.";
        YoutubeStatus.Foreground = state.YoutubeConnecting || state.YoutubeConnected
            ? new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(52, 211, 153))
            : new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(251, 191, 36));

        var selectedPageCount = state.FacebookPages.Count(page => page.Selected);
        FacebookStatus.Text = state.FacebookConnecting
            ? "CONNECTING  |  Complete Facebook authorization in your browser..."
            : state.FacebookConnected
                ? $"CONNECTED  |  Facebook Business Portfolio - {state.FacebookPages.Count} Page(s) available, {selectedPageCount} selected."
                : "NOT CONNECTED  |  Enter your Meta App ID, App Secret and Business Portfolio ID, then connect.";
        FacebookStatus.Foreground = state.FacebookConnecting || state.FacebookConnected
            ? new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(52, 211, 153))
            : new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(251, 191, 36));

        var youtubeHeader = state.YoutubeConnecting
            ? "YouTube: Connecting"
            : state.YoutubeConnected ? "YouTube: Connected" : "YouTube: Not connected";
        var facebookHeader = state.FacebookConnecting
            ? "FB: Connecting"
            : state.FacebookConnected ? $"FB: {state.FacebookPages.Count} Pages" : "FB: Not connected";
        ConnectionSummary.Text = $"{youtubeHeader}  |  {facebookHeader}";

        UpdatePages(state.FacebookPages);
        UpdateRows(state.Rows);
        UpdateSummary(state);
        UpdateButtons(state);
    }

    private void ApplyScheduleInputs(NativeState state)
    {
        _applyingScheduleInputs = true;
        try
        {
            StartDate.DisplayDateStart = DateTime.Today;
            if (DateTime.TryParse(state.StartAt, out var start) &&
                start.Date >= DateTime.Today && start > DateTime.Now)
            {
                SetStartDateTime(start);
            }
            else
            {
                SetDefaultStartTime();
            }

            var interval = Math.Clamp(state.IntervalMinutes, 5, 1440);
            IntervalHours.Text = (interval / 60).ToString();
            IntervalMinutes.Text = (interval % 60).ToString();
        }
        finally
        {
            _applyingScheduleInputs = false;
        }
        _startTimeConfirmed = false;
        _confirmedStartAt = null;
        StartConfirmationText.Text = "Start time not confirmed.";
        StartConfirmationText.Foreground = new System.Windows.Media.SolidColorBrush(
            System.Windows.Media.Color.FromRgb(251, 191, 36));
    }

    private static void SetTextWhenNotFocused(TextBox box, string value)
    {
        if (!box.IsKeyboardFocusWithin && !string.Equals(box.Text, value, StringComparison.Ordinal))
            box.Text = value;
    }

    private void UpdatePages(IEnumerable<PageDto> incoming)
    {
        var byId = Pages.ToDictionary(p => p.Id, StringComparer.Ordinal);
        var desired = incoming.ToList();
        var keep = desired.Select(p => p.Id).ToHashSet(StringComparer.Ordinal);
        foreach (var existing in Pages.ToList())
        {
            if (!keep.Contains(existing.Id))
                Pages.Remove(existing);
        }
        foreach (var page in desired)
        {
            if (byId.TryGetValue(page.Id, out var current))
            {
                current.Name = page.Name;
                current.Selected = page.Selected;
            }
            else
            {
                Pages.Add(page);
            }
        }
    }

    private void UpdateRows(IReadOnlyList<ClipDto> incoming)
    {
        var selectedPaths = ClipGrid.SelectedItems.Cast<ClipRow>()
            .Select(row => row.Path).ToHashSet(StringComparer.OrdinalIgnoreCase);

        var desired = incoming
            .Where(row => _showAllAccepted || !IsFullyAccepted(row.QueueStatus))
            .ToList();
        var wantedPaths = desired.Select(row => row.Path)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);

        // Incremental collection diff: update existing row models, only insert/remove
        // changed rows, and never clear/recreate the whole DataGrid.
        for (var index = 0; index < desired.Count; index++)
        {
            var dto = desired[index];
            if (!_rowsByPath.TryGetValue(dto.Path, out var row))
            {
                row = new ClipRow();
                row.Update(dto, index + 1);
                _rowsByPath[dto.Path] = row;
                Clips.Insert(Math.Min(index, Clips.Count), row);
            }
            else
            {
                row.Update(dto, index + 1);
                var currentIndex = Clips.IndexOf(row);
                if (currentIndex >= 0 && currentIndex != index)
                    Clips.Move(currentIndex, Math.Min(index, Clips.Count - 1));
            }
        }

        foreach (var row in Clips.ToList())
        {
            if (!wantedPaths.Contains(row.Path))
            {
                Clips.Remove(row);
                _rowsByPath.Remove(row.Path);
            }
        }

        // Keep a row selected when a status refresh changes another row.
        foreach (var row in Clips.Where(row => selectedPaths.Contains(row.Path)).ToList())
        {
            if (!ClipGrid.SelectedItems.Contains(row))
                ClipGrid.SelectedItems.Add(row);
        }
        UpdateSelectionSummary();
    }

    private static bool IsFullyAccepted(string status) =>
        string.Equals(status, "Scheduled", StringComparison.Ordinal) ||
        string.Equals(status, "Published", StringComparison.Ordinal);

    private void UpdateSummary(NativeState state)
    {
        int Count(string key) => state.Counts.TryGetValue(key, out var value) ? value : 0;
        var accepted = Count("Scheduled") + Count("Published");
        var pending = Count("Pending") + Count("Choose platform");
        var uploading = Count("Uploading");
        var failed = Count("Failed") + Count("Skipped");
        var partial = Count("Partial");
        var uploaded = Count("Uploaded");
        var visible = _showAllAccepted ? state.Total : Math.Max(0, state.Total - accepted);
        QueueSummary.Text =
            $"{state.Total} clips  |  {visible} visible  |  {pending} pending  |  " +
            $"{uploading} uploading  |  {partial} partial  |  {uploaded} uploaded  |  " +
            $"{accepted} scheduled/published  |  {failed} failed";
        FooterStatus.Text = state.Busy
            ? $"Background task active - queue: {(state.QueueRunning ? "running" : "idle")}, " +
              $"scan: {(state.ScanRunning ? "running" : "idle")}, verify: {(state.VerificationRunning ? "running" : "idle")}."
            : "Ready. No background operation is currently running.";
    }

    private void UpdateButtons(NativeState state)
    {
        var serviceReady = _api is not null;
        var busy = state.Busy;
        foreach (var button in new[] { NavQueue, NavConnections, NavActivity, NavHowTo })
            button.IsEnabled = serviceReady;
        ConfirmStartButton.IsEnabled = serviceReady && !busy;

        ScanButton.IsEnabled = serviceReady && !busy;
        ScheduleButton.IsEnabled = serviceReady && !busy;
        StopButton.IsEnabled = serviceReady && state.QueueRunning;
        VerifyButton.IsEnabled = serviceReady && !busy;
        ResetFailedButton.IsEnabled = serviceReady && !busy;

        ConnectYoutubeButton.Content = state.YoutubeConnecting
            ? "Reconnecting..." : state.YoutubeConnected ? "Reconnect YouTube" : "Connect YouTube";
        DisconnectYoutubeButton.Visibility = state.YoutubeConnected ? Visibility.Visible : Visibility.Collapsed;
        ConnectFacebookButton.Content = state.FacebookConnecting
            ? "Connecting..." : state.FacebookConnected ? "Reconnect Facebook" : "Connect Facebook";
        DisconnectFacebookButton.Visibility = state.FacebookConnected ? Visibility.Visible : Visibility.Collapsed;

        ConnectYoutubeButton.IsEnabled = serviceReady && !busy;
        DisconnectYoutubeButton.IsEnabled = serviceReady && !busy;
        ConnectFacebookButton.IsEnabled = serviceReady && !busy;
        DisconnectFacebookButton.IsEnabled = serviceReady && !busy;
    }

    private void UpdateSelectionSummary()
    {
        var selected = ClipGrid.SelectedItems.Count;
        SelectionSummary.Text = selected switch
        {
            0 => "0 selected — entire queue",
            1 => "1 selected — one clip",
            _ => $"{selected} selected — batch"
        };
    }

    private void ClipGrid_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        UpdateSelectionSummary();
        var row = ClipGrid.SelectedItems.Cast<ClipRow>().FirstOrDefault();
        if (row is null)
        {
            _selectedMetadataPath = null;
            MetadataTitle.Text = "";
            MetadataDescription.Text = "";
            return;
        }

        _selectedMetadataPath = row.Path;
        MetadataTitle.Text = row.Title;
        MetadataDescription.Text = row.Description;
    }

    private async void BrowseFolder_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFolderDialog
        {
            Title = "Choose the MP4/TXT clip folder",
            InitialDirectory = Directory.Exists(FolderBox.Text) ? FolderBox.Text : Environment.GetFolderPath(Environment.SpecialFolder.MyVideos),
            Multiselect = false
        };
        if (dialog.ShowDialog(this) == true)
        {
            FolderBox.Text = dialog.FolderName;
            await SaveSettingsAsync();
        }
    }

    private async void BrowseClientSecrets_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFileDialog
        {
            Title = "Select Google OAuth Desktop client JSON",
            Filter = "JSON files (*.json)|*.json|All files (*.*)|*.*",
            CheckFileExists = true
        };
        if (dialog.ShowDialog(this) == true)
        {
            ClientSecretsBox.Text = dialog.FileName;
            await SaveSettingsAsync();
        }
    }

    private void SetStartDateTime(DateTime value)
    {
        StartDate.SelectedDate = value.Date;
        var hour12 = value.Hour % 12;
        StartHour.SelectedIndex = hour12 == 0 ? 11 : hour12 - 1;
        StartMinute.Text = value.Minute.ToString("D2");
        StartAmPm.SelectedIndex = value.Hour >= 12 ? 1 : 0;
    }

    private void SetDefaultStartTime()
    {
        // Match the scheduler's 15-minute minimum lead time, rounded up to
        // the next quarter-hour so the default can never already be past.
        var target = DateTime.Now.AddMinutes(15);
        var remainder = target.Minute % 15;
        if (remainder != 0 || target.Second != 0 || target.Millisecond != 0)
            target = target.AddMinutes(15 - remainder);
        target = new DateTime(target.Year, target.Month, target.Day, target.Hour, target.Minute, 0);
        SetStartDateTime(target);
    }

    private void ScheduleInput_Changed(object sender, RoutedEventArgs e)
    {
        if (!_initialStateApplied || _applyingScheduleInputs)
            return;
        _startTimeConfirmed = false;
        _confirmedStartAt = null;
        StartConfirmationText.Text = "Changed ? confirm the start time again.";
        StartConfirmationText.Foreground = new System.Windows.Media.SolidColorBrush(
            System.Windows.Media.Color.FromRgb(251, 191, 36));
    }

    private void StartMinute_PreviewTextInput(object sender, System.Windows.Input.TextCompositionEventArgs e)
    {
        e.Handled = !e.Text.All(char.IsDigit);
    }

    private DateTime GetSelectedStartDateTime()
    {
        if (StartDate.SelectedDate is not DateTime selectedDate)
            throw new InvalidOperationException("Choose the first post date.");

        if (StartHour.SelectedItem is not ComboBoxItem hourItem ||
            !int.TryParse(hourItem.Content?.ToString(), out var hour12) ||
            hour12 < 1 || hour12 > 12)
            throw new InvalidOperationException("Choose an hour between 1 and 12.");

        if (!int.TryParse(StartMinute.Text.Trim(), out var minute) || minute < 0 || minute > 59)
            throw new InvalidOperationException("Enter minutes as a number from 00 to 59.");

        var period = (StartAmPm.SelectedItem as ComboBoxItem)?.Content?.ToString();
        if (period is not ("AM" or "PM"))
            throw new InvalidOperationException("Choose AM or PM.");

        var hour24 = (hour12 % 12) + (period == "PM" ? 12 : 0);
        return new DateTime(selectedDate.Year, selectedDate.Month, selectedDate.Day, hour24, minute, 0);
    }

    private void NavQueue_Click(object sender, RoutedEventArgs e) => ShowPage("queue");
    private void NavConnections_Click(object sender, RoutedEventArgs e) => ShowPage("connections");
    private void NavActivity_Click(object sender, RoutedEventArgs e) => ShowPage("activity");
    private void NavHowTo_Click(object sender, RoutedEventArgs e) => ShowPage("howto");

    private void ShowPage(string page)
    {
        QueuePage.Visibility = page == "queue" ? Visibility.Visible : Visibility.Collapsed;
        ConnectionsPage.Visibility = page == "connections" ? Visibility.Visible : Visibility.Collapsed;
        ActivityPage.Visibility = page == "activity" ? Visibility.Visible : Visibility.Collapsed;
        HowToPage.Visibility = page == "howto" ? Visibility.Visible : Visibility.Collapsed;
        NavQueue.Background = page == "queue" ? new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(48, 33, 83)) : System.Windows.Media.Brushes.Transparent;
        NavConnections.Background = page == "connections" ? new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(48, 33, 83)) : System.Windows.Media.Brushes.Transparent;
        NavActivity.Background = page == "activity" ? new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(48, 33, 83)) : System.Windows.Media.Brushes.Transparent;
        NavHowTo.Background = page == "howto" ? new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(48, 33, 83)) : System.Windows.Media.Brushes.Transparent;
    }

    private void HideAccepted_Changed(object sender, RoutedEventArgs e)
    {
        if (HideAcceptedCheck is null || _state is null)
            return;
        _showAllAccepted = HideAcceptedCheck.IsChecked != true;
        UpdateRows(_state.Rows);
        UpdateSummary(_state);
    }

    private void SelectAll_Click(object sender, RoutedEventArgs e) => ClipGrid.SelectAll();
    private void UnselectAll_Click(object sender, RoutedEventArgs e) => ClipGrid.UnselectAll();

    private async void Scan_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            await SaveSettingsAsync();
            await RequireApi().PostAsync("api/scan", BuildSettingsPayload());
            FooterStatus.Text = "Folder scan started in the background.";
            await RefreshStateAsync();
        }
        catch (Exception ex) { ShowError("Scan could not start", ex.Message); }
    }

    private async void ConfirmStartTime_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var settings = BuildSettingsPayload();
            var start = GetSelectedStartDateTime();
            var minimum = DateTime.Now.AddMinutes(15);
            if (start < minimum)
            {
                _startTimeConfirmed = false;
                _confirmedStartAt = null;
                ShowWarning("Choose a later start time",
                    "The first post must be at least 15 minutes from now. Change the time and confirm it again.");
                return;
            }

            await RequireApi().PostAsync("api/settings", settings);
            _confirmedStartAt = start;
            _confirmedInterval = (int)settings["interval_minutes"]!;
            _startTimeConfirmed = true;
            var interval = TimeSpan.FromMinutes(_confirmedInterval);
            StartConfirmationText.Text =
                $"CONFIRMED: {start:ddd, dd MMM yyyy h:mm tt} | every " +
                $"{(int)interval.TotalHours}h {interval.Minutes}m";
            StartConfirmationText.Foreground = new System.Windows.Media.SolidColorBrush(
                System.Windows.Media.Color.FromRgb(52, 211, 153));
            FooterStatus.Text = "Start time and interval confirmed and saved.";
            AddActivity($"Start time confirmed: {start:yyyy-MM-dd HH:mm}; interval {_confirmedInterval} minutes.");
        }
        catch (Exception ex) { ShowError("Start time could not be confirmed", ex.Message); }
    }

    private async void Schedule_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var selectedStart = GetSelectedStartDateTime();
            var selectedSettings = BuildSettingsPayload();
            if (!_startTimeConfirmed || _confirmedStartAt != selectedStart ||
                _confirmedInterval != (int)selectedSettings["interval_minutes"]!)
            {
                ShowWarning("Confirm the start time first",
                    "Click Confirm start time after choosing the date, time, and interval. Any later edits require a new confirmation.");
                return;
            }
            if (selectedStart < DateTime.Now.AddMinutes(15))
            {
                _startTimeConfirmed = false;
                _confirmedStartAt = null;
                ShowWarning("Confirm a later start time",
                    "The selected first-post time is now too close. Choose a time at least 15 minutes ahead and confirm it again.");
                return;
            }

            if (RightsCheck.IsChecked != true)
            {
                ShowWarning("Publishing rights", "Confirm that you own these clips or have permission to repost them and that the uploads comply with platform rules.");
                return;
            }

            StartDate.DisplayDateStart = DateTime.Today;
            var settings = selectedSettings;
            var requestedStart = DateTime.Parse((string)settings["start_at"]!);
            if (requestedStart <= DateTime.Now)
            {
                ShowWarning(
                    "Choose a future time",
                    "The first post date and time must be later than your current local time. Choose a later time or a future date.");
                return;
            }

            var selected = ClipGrid.SelectedItems.Cast<ClipRow>().Select(row => row.Path).ToList();
            settings["selected_paths"] = selected;
            settings["rights_confirmed"] = true;
            var selectedPages = Pages.Where(page => page.Selected).Select(page => page.Id).ToList();
            settings["selected_page_ids"] = selectedPages;

            var startAt = (string)settings["start_at"]!;
            var interval = (int)settings["interval_minutes"]!;
            var selectedCount = selected.Count == 0 ? (_state?.Total ?? 0) : selected.Count;
            var platforms = string.Join(" + ", new[]
            {
                YoutubeCheck.IsChecked == true ? "YouTube" : null,
                FacebookCheck.IsChecked == true ? "Facebook Pages" : null
            }.Where(value => value is not null));
            if (string.IsNullOrWhiteSpace(platforms))
            {
                ShowWarning("Choose a platform", "Select YouTube, Facebook, or both.");
                return;
            }

            var prompt =
                $"Schedule up to {selectedCount} selected clip(s)?\n\n" +
                $"First post: {startAt} local time\n" +
                $"Interval: {interval / 60} hour(s), {interval % 60} minute(s)\n" +
                $"Platforms: {platforms}\n" +
                $"Facebook Pages: {(selectedPages.Count == 0 ? "none selected" : string.Join(", ", Pages.Where(page => page.Selected).Select(page => page.Name)))}\n\n" +
                "The first clip uses the confirmed start time; later clips follow the chosen interval. " +
                "YouTube and Facebook quota limits can defer remaining work to the next eligible day. " +
                "Rejected destinations receive a tomorrow retry slot. Already accepted platform schedules are never resubmitted.";
            if (MessageBox.Show(this, prompt, "Confirm scheduling", MessageBoxButton.YesNo, MessageBoxImage.Warning) != MessageBoxResult.Yes)
                return;

            settings["confirmed"] = true;
            using var result = await RequireApi().PostConfirmedAsync("api/schedule", settings);
            var started = result.RootElement.TryGetProperty("started", out var value) && value.GetBoolean();
            FooterStatus.Text = started ? "Publishing queue started." : "No pending destination work was started. Review the log.";
            await RefreshStateAsync();
        }
        catch (Exception ex) { ShowError("Scheduling could not start", ex.Message); }
    }

    private async void Stop_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            await RequireApi().PostAsync("api/stop", new { });
            FooterStatus.Text = "Stop requested. The current platform request is allowed to finish.";
            await RefreshStateAsync();
        }
        catch (Exception ex) { ShowError("Stop failed", ex.Message); }
    }

    private async void Verify_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            await RequireApi().PostAsync("api/verify", new { });
            FooterStatus.Text = "Publication verification started in the background.";
        }
        catch (Exception ex) { ShowError("Verification could not start", ex.Message); }
    }

    private async void ResetFailed_Click(object sender, RoutedEventArgs e)
    {
        if (MessageBox.Show(this, "Reset failed YouTube and Facebook destinations to Pending?\nSuccessfully accepted schedules will remain unchanged.",
                "Reset failed items", MessageBoxButton.YesNo, MessageBoxImage.Warning) != MessageBoxResult.Yes)
            return;
        try
        {
            await RequireApi().PostAsync("api/reset-failed", new { });
            await RefreshStateAsync();
        }
        catch (Exception ex) { ShowError("Reset failed", ex.Message); }
    }

    private async void ExportReport_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            using var result = await RequireApi().PostAsync("api/export-report", new { });
            var csv = result.RootElement.GetProperty("csv").GetString() ?? "";
            var txt = result.RootElement.GetProperty("txt").GetString() ?? "";
            AddActivity($"Cleanup report exported: {csv}");
            MessageBox.Show(this, $"Report files created:\n\nCSV:\n{csv}\n\nText:\n{txt}\n\nNo local videos were deleted.",
                "Cleanup report", MessageBoxButton.OK, MessageBoxImage.Information);
        }
        catch (Exception ex) { ShowError("Cleanup report failed", ex.Message); }
    }

    private async void DeleteSelected_Click(object sender, RoutedEventArgs e)
    {
        var paths = ClipGrid.SelectedItems.Cast<ClipRow>().Select(row => row.Path).ToList();
        if (paths.Count == 0)
        {
            ShowWarning("Select clips", "Select one or more clips first.");
            return;
        }
        var accepted = paths.Count(path => _state?.Rows.FirstOrDefault(row => row.Path == path) is { } row &&
            (row.YoutubeStatus is "Scheduled" or "Published" || row.FacebookStatus is "Scheduled" or "Published"));
        var prompt = $"Remove {paths.Count} selected video(s) from the local queue?\n\n" +
                     $"Accepted/scheduled destinations on these clips: {accepted}\n\n" +
                     "This removes local queue records only. It does not cancel YouTube or Facebook posts, " +
                     "and it does not delete MP4 or TXT files.";
        if (MessageBox.Show(this, prompt, "Delete selected queue entries", MessageBoxButton.YesNo, MessageBoxImage.Warning) != MessageBoxResult.Yes)
            return;
        try
        {
            await RequireApi().PostAsync("api/delete", new { paths });
            await RefreshStateAsync();
        }
        catch (Exception ex) { ShowError("Queue entries were not removed", ex.Message); }
    }

    private async void SaveMetadata_Click(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrWhiteSpace(_selectedMetadataPath))
        {
            ShowWarning("Select a clip", "Select a clip in the queue first.");
            return;
        }
        try
        {
            await RequireApi().PostAsync("api/metadata", new
            {
                path = _selectedMetadataPath,
                title = MetadataTitle.Text,
                description = MetadataDescription.Text
            });
            FooterStatus.Text = "Metadata saved.";
            await RefreshStateAsync();
        }
        catch (Exception ex) { ShowError("Metadata was not saved", ex.Message); }
    }

    private async void ConnectYoutube_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var settings = BuildSettingsPayload();
            using var result = await RequireApi().PostAsync("api/connect-youtube", settings);
            FooterStatus.Text = "YouTube authorization opened in your browser.";
        }
        catch (Exception ex) { ShowError("YouTube connection failed", ex.Message); }
    }

    private async void ConnectFacebook_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var settings = BuildSettingsPayload();
            using var result = await RequireApi().PostAsync("api/connect-facebook", settings);
            FooterStatus.Text = "Facebook authorization opened in your browser.";
        }
        catch (Exception ex) { ShowError("Facebook connection failed", ex.Message); }
    }

    private async void DisconnectYoutube_Click(object sender, RoutedEventArgs e)
    {
        var answer = MessageBox.Show(this,
            "Disconnect the saved YouTube account from this PC?\n\n" +
            "The local Google OAuth token and displayed channel connection will be removed. " +
            "Videos already accepted and scheduled by YouTube will not be cancelled. " +
            "You can reconnect later using your OAuth Desktop client JSON.",
            "Disconnect YouTube", MessageBoxButton.YesNo, MessageBoxImage.Warning);
        if (answer != MessageBoxResult.Yes)
            return;
        try
        {
            await RequireApi().PostAsync("api/disconnect-youtube", new { });
            await RefreshStateAsync();
            FooterStatus.Text = "YouTube disconnected locally. Existing scheduled posts were preserved.";
        }
        catch (Exception ex) { ShowError("YouTube could not be disconnected", ex.Message); }
    }

    private async void DisconnectFacebook_Click(object sender, RoutedEventArgs e)
    {
        var answer = MessageBox.Show(this,
            "Disconnect the saved Facebook Business/Page accounts from this PC?\n\n" +
            "Saved Page access tokens and Page connection details will be removed locally. " +
            "Reconnecting will require Meta authorization again. Reels already accepted and scheduled by Facebook will not be cancelled. " +
            "This does not revoke the app from your Facebook account settings.",
            "Disconnect Facebook", MessageBoxButton.YesNo, MessageBoxImage.Warning);
        if (answer != MessageBoxResult.Yes)
            return;
        try
        {
            await RequireApi().PostAsync("api/disconnect-facebook", new { });
            await RefreshStateAsync();
            FooterStatus.Text = "Facebook disconnected locally. Existing Page Reel schedules were preserved.";
        }
        catch (Exception ex) { ShowError("Facebook could not be disconnected", ex.Message); }
    }

    private async void SavePages_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            await SaveSettingsAsync();
            FooterStatus.Text = $"Saved {Pages.Count(page => page.Selected)} selected Facebook Page(s).";
            await RefreshStateAsync();
        }
        catch (Exception ex) { ShowError("Facebook Page selection was not saved", ex.Message); }
    }

    private void ClearLog_Click(object sender, RoutedEventArgs e) => ActivityList.Items.Clear();

    private async Task SaveSettingsAsync()
    {
        if (_api is null)
            return;
        await RequireApi().PostAsync("api/settings", BuildSettingsPayload());
    }

    private Dictionary<string, object?> BuildSettingsPayload()
    {
        var start = GetSelectedStartDateTime();
        if (StartDate.SelectedDate!.Value.Date < DateTime.Today)
            throw new InvalidOperationException("The first post date cannot be earlier than today.");
        if (!int.TryParse(IntervalHours.Text, out var hours) || hours < 0 || hours > 24)
            throw new InvalidOperationException("Hours must be between 0 and 24.");
        if (!int.TryParse(IntervalMinutes.Text, out var minutes) || minutes < 0 || minutes > 59)
            throw new InvalidOperationException("Minutes must be between 0 and 59.");
        if (hours == 24 && minutes != 0)
            throw new InvalidOperationException("A 24-hour interval cannot contain additional minutes.");
        var total = hours * 60 + minutes;
        if (total < 5 || total > 1440)
            throw new InvalidOperationException("The interval must be between 5 minutes and 24 hours.");

        var category = (CategoryBox.SelectedItem as ComboBoxItem)?.Tag?.ToString() ?? "20";
        return new Dictionary<string, object?>
        {
            ["folder"] = FolderBox.Text.Trim(),
            ["start_at"] = start.ToString("yyyy-MM-dd HH:mm"),
            ["interval_minutes"] = total,
            ["youtube_enabled"] = YoutubeCheck.IsChecked == true,
            ["facebook_enabled"] = FacebookCheck.IsChecked == true,
            ["youtube_ai"] = YoutubeAiCheck.IsChecked == true,
            ["facebook_ai"] = FacebookAiCheck.IsChecked == true,
            ["made_for_kids"] = MadeForKidsCheck.IsChecked == true,
            ["category_id"] = category,
            ["client_secrets"] = ClientSecretsBox.Text.Trim(),
            ["meta_app_id"] = MetaAppIdBox.Text.Trim(),
            ["meta_app_secret"] = MetaAppSecretBox.Password,
            ["business_id"] = BusinessIdBox.Text.Trim(),
            ["selected_page_ids"] = Pages.Where(page => page.Selected).Select(page => page.Id).ToList()
        };
    }

    private async Task<JsonDocument> SaveAndPostAsync(string route, object payload)
    {
        return await RequireApi().PostAsync(route, payload);
    }

    private ApiClient RequireApi() =>
        _api ?? throw new InvalidOperationException("The publishing service is not connected.");

    private static string GetString(JsonElement element, string name) =>
        element.ValueKind == JsonValueKind.Object &&
        element.TryGetProperty(name, out var value)
            ? value.GetString() ?? ""
            : "";

    private void ShowBackendDialog(JsonElement data)
    {
        var title = GetString(data, "title");
        var message = GetString(data, "message");
        var kind = GetString(data, "kind");
        if (string.IsNullOrWhiteSpace(message))
            return;
        var icon = kind switch
        {
            "error" => MessageBoxImage.Error,
            "warning" => MessageBoxImage.Warning,
            _ => MessageBoxImage.Information
        };
        MessageBox.Show(this, message, string.IsNullOrWhiteSpace(title) ? "ScarClipScheduler" : title,
            MessageBoxButton.OK, icon);
    }

    private void AddActivity(string message)
    {
        if (string.IsNullOrWhiteSpace(message))
            return;
        ActivityList.Items.Add(message);
        while (ActivityList.Items.Count > 6000)
            ActivityList.Items.RemoveAt(0);
        ActivityList.ScrollIntoView(ActivityList.Items[ActivityList.Items.Count - 1]);
    }

    private void ShowWarning(string title, string message) =>
        MessageBox.Show(this, message, title, MessageBoxButton.OK, MessageBoxImage.Warning);

    private void ShowError(string title, string message) =>
        MessageBox.Show(this, message, title, MessageBoxButton.OK, MessageBoxImage.Error);

    private void About_Click(object sender, RoutedEventArgs e)
    {
        var content = new StackPanel { Margin = new Thickness(24) };
        content.Children.Add(new TextBlock
        {
            Text = "ScarClipScheduler",
            FontSize = 25,
            FontWeight = FontWeights.Bold,
            Foreground = new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(225, 215, 255)),
            Margin = new Thickness(0, 0, 0, 3)
        });
        content.Children.Add(new TextBlock
        {
            Text = "Version 2.0.15  |  Native Windows application",
            FontSize = 12,
            Foreground = new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(154, 168, 196)),
            Margin = new Thickness(0, 0, 0, 14)
        });
        AddAboutHeading(content, "CREDITS");
        AddAboutText(content, "Created and maintained by Sifat Jaman / ScarZero.");
        AddAboutText(content, "Built with development assistance from ChatGPT by OpenAI. Project ownership, direction and release decisions remain with the creator.");
        AddAboutHeading(content, "GITHUB");
        AddAboutLink(content, "GitHub profile - sifat-jaman-13", "https://github.com/sifat-jaman-13");
        AddAboutLink(content, "ScarClipScheduler repository", "https://github.com/sifat-jaman-13/youtube-shorts-facebook-reels-scheduler");
        AddAboutLink(content, "StreamSnip AI repository", "https://github.com/sifat-jaman-13/stream-clip-ai");
        AddAboutHeading(content, "YOUTUBE CHANNELS");
        if (_state?.YoutubeConnected == true && !string.IsNullOrWhiteSpace(_state.YoutubeChannelId))
        {
            var channelName = string.IsNullOrWhiteSpace(_state.YoutubeChannel) ? "Connected YouTube channel" : _state.YoutubeChannel;
            AddAboutLink(content, channelName, $"https://www.youtube.com/channel/{Uri.EscapeDataString(_state.YoutubeChannelId)}");
        }
        else
        {
            AddAboutText(content, "No YouTube channel is currently connected.");
        }
        AddAboutLink(content, "Scar Clip Farm", "https://youtube.com/@scarclipfarm");
        AddAboutLink(content, "ScarZero YouTube channel", "https://www.youtube.com/@scarzeroyt");
        AddAboutHeading(content, "OTHER CHANNELS");
        AddAboutLink(content, "Instagram - @scarzero13", "https://www.instagram.com/scarzero13/");
        AddAboutLink(content, "Facebook - ScarZero13", "https://www.facebook.com/ScarZero13");
        AddAboutLink(content, "Twitch - scarzero13", "https://www.twitch.tv/scarzero13");
        AddAboutLink(content, "TikTok - @scarzero13", "https://www.tiktok.com/@scarzero13");

        var close = new Button
        {
            Content = "Close",
            Width = 100,
            HorizontalAlignment = HorizontalAlignment.Right,
            Margin = new Thickness(0, 16, 0, 0),
            Padding = new Thickness(15, 8, 15, 8)
        };
        content.Children.Add(close);

        var aboutWindow = new Window
        {
            Title = "About ScarClipScheduler",
            Owner = this,
            Width = 570,
            Height = 720,
            MinWidth = 520,
            MinHeight = 560,
            MaxHeight = SystemParameters.WorkArea.Height - 40,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
            ResizeMode = ResizeMode.CanResize,
            Background = new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(11, 16, 32)),
            Foreground = new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(241, 245, 255)),
            Content = new ScrollViewer
            {
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                Content = content
            }
        };
        close.Click += (_, _) => aboutWindow.Close();
        aboutWindow.ShowDialog();
    }

    private static void AddAboutHeading(Panel panel, string text)
    {
        panel.Children.Add(new TextBlock
        {
            Text = text,
            FontSize = 11,
            FontWeight = FontWeights.Bold,
            Foreground = new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(191, 170, 255)),
            Margin = new Thickness(0, 13, 0, 5)
        });
    }

    private static void AddAboutText(Panel panel, string text, bool italic = false)
    {
        panel.Children.Add(new TextBlock
        {
            Text = text,
            FontSize = 13,
            TextWrapping = TextWrapping.Wrap,
            FontStyle = italic ? FontStyles.Italic : FontStyles.Normal,
            Foreground = new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(205, 215, 234)),
            Margin = new Thickness(0, 2, 0, 5)
        });
    }

    private void AddAboutLink(Panel panel, string label, string url)
    {
        var line = new TextBlock
        {
            FontSize = 13,
            Margin = new Thickness(0, 2, 0, 4),
            TextWrapping = TextWrapping.Wrap
        };
        var link = new Hyperlink(new Run(label))
        {
            NavigateUri = new Uri(url),
            Foreground = new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(174, 149, 255))
        };
        link.RequestNavigate += (_, e) =>
        {
            try
            {
                Process.Start(new ProcessStartInfo(e.Uri.AbsoluteUri) { UseShellExecute = true });
            }
            catch (Exception ex)
            {
                ShowError("Could not open the link", ex.Message);
            }
            e.Handled = true;
        };
        line.Inlines.Add(link);
        panel.Children.Add(line);
    }

    private async void Quit_Click(object sender, RoutedEventArgs e) => await RequestCloseAsync();

    private async void Window_Closing(object? sender, CancelEventArgs e)
    {
        if (_allowClose)
            return;
        e.Cancel = true;
        await RequestCloseAsync();
    }

    private async Task RequestCloseAsync()
    {
        if (_allowClose || _shutdownInProgress)
            return;
        _shutdownInProgress = true;
        try
        {
            if (_api is not null && _state?.Busy == true)
            {
                var answer = MessageBox.Show(this,
                    "A scan, publication check, or publishing queue is still active.\n\n" +
                    "Stop pending work, allow the current platform request to finish, and then close?",
                    "Background work is active", MessageBoxButton.YesNo, MessageBoxImage.Warning);
                if (answer != MessageBoxResult.Yes)
                    return;

                if (_state.QueueRunning)
                    await _api.PostAsync("api/stop", new { });

                FooterStatus.Text = "Waiting for the active operation to finish before closing...";
                var deadline = DateTime.UtcNow.AddMinutes(5);
                while (DateTime.UtcNow < deadline)
                {
                    await Task.Delay(500);
                    _state = await _api.GetStateAsync();
                    if (!_state.Busy)
                        break;
                    FooterStatus.Text = "Waiting for the current upload / scan / verification request...";
                }
                if (_state.Busy)
                {
                    var force = MessageBox.Show(this,
                        "The background operation is still active after five minutes. Close and interrupt it?",
                        "Worker still active", MessageBoxButton.YesNo, MessageBoxImage.Warning);
                    if (force != MessageBoxResult.Yes)
                        return;
                }
            }

            _eventTimer.Stop();
            if (_backend is not null)
                await _backend.DisposeAsync();
            _allowClose = true;
            Close();
        }
        catch (Exception ex)
        {
            ShowError("Close failed", ex.Message);
        }
        finally
        {
            _shutdownInProgress = false;
        }
    }
}
