using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Collections.Generic;

internal static class Program
{
    private const string AppVersion = "1.3.0";
    private static string InstallDirectory;

    private sealed class CommandResult
    {
        public int ExitCode;
        public string Output;
        public string Error;
    }

    private static int Main(string[] args)
    {
        Console.OutputEncoding = Encoding.UTF8;
        Console.Title = "ScarClipScheduler - setup and launch";
        Console.WriteLine("====================================================");
        Console.WriteLine("  ScarClipScheduler " + AppVersion);
        Console.WriteLine("  First-run setup and dependency manager");
        Console.WriteLine("====================================================");
        Console.WriteLine();

        try
        {
            if (args != null && args.Length > 0 &&
                String.Equals(args[0], "--verify-package", StringComparison.OrdinalIgnoreCase))
                return VerifyPackageResources();
            return InstallAndLaunch();
        }
        catch (Exception ex)
        {
            Console.WriteLine();
            Console.WriteLine("SETUP / LAUNCH FAILED");
            Console.WriteLine(ex.Message);
            Console.WriteLine();
            Console.WriteLine("Check your internet connection and the log in:");
            Console.WriteLine(Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "ScarClipScheduler", "app.log"));
            Console.WriteLine();
            Console.Write("Press Enter to close this window...");
            Console.ReadLine();
            return 1;
        }
    }

    private static int InstallAndLaunch()
    {
        string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        InstallDirectory = Path.Combine(localAppData, "Programs", "ScarClipScheduler");
        Directory.CreateDirectory(InstallDirectory);

        string appPath = Path.Combine(InstallDirectory, "app.py");
        string requirementsPath = Path.Combine(InstallDirectory, "requirements.txt");
        string assetsDirectory = Path.Combine(InstallDirectory, "assets");
        Directory.CreateDirectory(assetsDirectory);
        ExtractResource("ScarClipScheduler.app.py", appPath);
        ExtractResource("ScarClipScheduler.requirements.txt", requirementsPath);
        ExtractResource("ScarClipScheduler.logo.png", Path.Combine(assetsDirectory, "scarclipscheduler-logo.png"));
        ExtractResource("ScarClipScheduler.logo.ico", Path.Combine(assetsDirectory, "scarclipscheduler.ico"));

        Console.WriteLine("[1/4] Checking for Python 3.11 or newer...");
        string python = FindPython();

        if (String.IsNullOrEmpty(python))
        {
            string winget = FindOnPath("winget.exe");
            if (String.IsNullOrEmpty(winget))
            {
                Process.Start(new ProcessStartInfo("https://www.python.org/downloads/windows/") {
                    UseShellExecute = true
                });
                throw new InvalidOperationException(
                    "Python 3.11+ was not found and winget is unavailable. Install Python 3.12 " +
                    "from the page opened in your browser, enable the Python launcher, then run this EXE again.");
            }

            Console.WriteLine("Python was not found. Installing Python 3.12 for this Windows user with winget...");
            int installCode = RunAndWait(
                winget,
                "install --id Python.Python.3.12 -e --scope user --accept-package-agreements --accept-source-agreements",
                InstallDirectory
            );
            if (installCode != 0)
                throw new InvalidOperationException("winget could not install Python 3.12 (exit code " + installCode + ").");

            python = FindPython();
            if (String.IsNullOrEmpty(python))
                throw new InvalidOperationException(
                    "Python installation finished, but the Python executable could not be located. " +
                    "Close this terminal, open it again, and run ScarClipScheduler.");
        }

        Console.WriteLine("Using: " + python);
        Console.WriteLine();

        Console.WriteLine("[2/4] Preparing the isolated application environment...");
        string venvDirectory = Path.Combine(InstallDirectory, ".venv");
        string venvPython = Path.Combine(venvDirectory, "Scripts", "python.exe");
        string pythonMarker = Path.Combine(InstallDirectory, ".python-runtime");

        bool rebuildVenv = !File.Exists(venvPython) ||
            !IsUsablePython(venvPython) || !File.Exists(pythonMarker);
        if (!rebuildVenv && File.Exists(pythonMarker))
        {
            string previousPython = File.ReadAllText(pythonMarker).Trim();
            rebuildVenv = !String.Equals(previousPython, python, StringComparison.OrdinalIgnoreCase);
        }

        if (rebuildVenv)
        {
            if (Directory.Exists(venvDirectory))
                Directory.Delete(venvDirectory, true);
            int venvCode = RunAndWait(python, "-m venv " + Quote(venvDirectory), InstallDirectory);
            if (venvCode != 0 || !File.Exists(venvPython))
                throw new InvalidOperationException("Could not create the isolated Python environment.");
            File.WriteAllText(pythonMarker, python, Encoding.UTF8);
        }

        Console.WriteLine();
        Console.WriteLine("[3/4] Checking and installing Python packages...");
        string dependencyMarker = Path.Combine(InstallDirectory, ".dependencies-version");
        bool installDependencies =
            !File.Exists(dependencyMarker) ||
            !String.Equals(File.ReadAllText(dependencyMarker).Trim(), AppVersion, StringComparison.Ordinal) ||
            !PythonImportsAvailable(venvPython);

        if (installDependencies)
        {
            Console.WriteLine("Installing the required packages from the internet. This happens on first launch and after app updates.");
            int pipCode = RunAndWait(
                venvPython,
                "-m pip install --upgrade pip",
                InstallDirectory
            );
            if (pipCode != 0)
                throw new InvalidOperationException("pip could not be upgraded. Check your internet connection.");

            int requirementsCode = RunAndWait(
                venvPython,
                "-m pip install --upgrade -r " + Quote(requirementsPath),
                InstallDirectory
            );
            if (requirementsCode != 0)
                throw new InvalidOperationException("Python dependencies could not be installed from requirements.txt.");

            if (!PythonImportsAvailable(venvPython))
                throw new InvalidOperationException("Package installation completed, but an application dependency is still missing.");

            File.WriteAllText(dependencyMarker, AppVersion, Encoding.UTF8);
        }
        else
        {
            Console.WriteLine("Required packages are already installed.");
        }

        Console.WriteLine();
        Console.WriteLine("[4/4] Launching ScarClipScheduler...");
        Console.WriteLine("The application and virtual environment are stored in:");
        Console.WriteLine(InstallDirectory);
        Console.WriteLine("Your queue, settings, and API credentials remain in %LOCALAPPDATA%\\ScarClipScheduler.");
        Console.WriteLine();

        int appExit = RunAndWait(venvPython, Quote(appPath), InstallDirectory);
        if (appExit != 0)
            Console.WriteLine("ScarClipScheduler exited with code " + appExit + ".");
        return appExit;
    }

    private static int VerifyPackageResources()
    {
        string temp = Path.Combine(Path.GetTempPath(), "ScarClipScheduler-PackageVerification");
        if (Directory.Exists(temp))
            Directory.Delete(temp, true);
        Directory.CreateDirectory(temp);
        InstallDirectory = temp;

        string appPath = Path.Combine(temp, "app.py");
        string requirementsPath = Path.Combine(temp, "requirements.txt");
        string assetsDirectory = Path.Combine(temp, "assets");
        Directory.CreateDirectory(assetsDirectory);
        string logoPath = Path.Combine(assetsDirectory, "scarclipscheduler-logo.png");
        string iconPath = Path.Combine(assetsDirectory, "scarclipscheduler.ico");
        ExtractResource("ScarClipScheduler.app.py", appPath);
        ExtractResource("ScarClipScheduler.requirements.txt", requirementsPath);
        ExtractResource("ScarClipScheduler.logo.png", logoPath);
        ExtractResource("ScarClipScheduler.logo.ico", iconPath);

        if (new FileInfo(appPath).Length < 10000 || new FileInfo(requirementsPath).Length < 20 ||
            new FileInfo(logoPath).Length < 10000 || new FileInfo(iconPath).Length < 1000)
            throw new InvalidOperationException("The embedded app, requirements, or branding resources are incomplete.");

        string python = FindPython();
        if (String.IsNullOrEmpty(python))
            throw new InvalidOperationException("Package resources extracted, but Python 3.11+ is not available for the syntax check.");

        CommandResult result = RunCapture(python, "-m py_compile " + Quote(appPath), temp);
        if (result.ExitCode != 0)
            throw new InvalidOperationException("The embedded app.py failed the Python compile check: " + result.Error);

        Console.WriteLine("PACKAGE_VERIFICATION=PASSED");
        Console.WriteLine("Embedded app.py bytes: " + new FileInfo(appPath).Length);
        Console.WriteLine("Embedded requirements.txt bytes: " + new FileInfo(requirementsPath).Length);
        Console.WriteLine("Python syntax check: passed");
        return 0;
    }

    private static void ExtractResource(string resourceName, string destination)
    {
        Assembly assembly = Assembly.GetExecutingAssembly();
        using (Stream input = assembly.GetManifestResourceStream(resourceName))
        {
            if (input == null)
                throw new InvalidOperationException("The EXE is missing its embedded application resource: " + resourceName);
            string directory = Path.GetDirectoryName(destination);
            if (!String.IsNullOrEmpty(directory))
                Directory.CreateDirectory(directory);
            using (FileStream output = File.Create(destination))
                input.CopyTo(output);
        }
    }

    private static bool PythonImportsAvailable(string python)
    {
        CommandResult result = RunCapture(
            python,
            "-c \"import requests, googleapiclient, google_auth_oauthlib, google.auth, tzdata\"",
            InstallDirectory
        );
        return result.ExitCode == 0;
    }

    private static string FindPython()
    {
        string py = FindOnPath("py.exe");
        if (!String.IsNullOrEmpty(py))
        {
            string[] launchers = new string[] { "-3.12", "-3.11" };
            foreach (string version in launchers)
            {
                CommandResult result = RunCapture(
                    py,
                    version + " -c \"import sys; print(sys.executable)\"",
                    InstallDirectory
                );
                if (result.ExitCode == 0)
                {
                    string candidate = LastNonEmptyLine(result.Output);
                    if (IsUsablePython(candidate))
                        return candidate;
                }
            }
        }

        string direct = FindOnPath("python.exe");
        if (IsUsablePython(direct))
            return direct;

        string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        string programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
        string[] known = new string[] {
            Path.Combine(local, "Programs", "Python", "Python312", "python.exe"),
            Path.Combine(local, "Programs", "Python", "Python311", "python.exe"),
            Path.Combine(programFiles, "Python312", "python.exe"),
            Path.Combine(programFiles, "Python311", "python.exe"),
            @"C:\Python312\python.exe",
            @"C:\Python311\python.exe"
        };
        foreach (string candidate in known)
            if (IsUsablePython(candidate))
                return candidate;
        return null;
    }

    private static bool IsUsablePython(string candidate)
    {
        if (String.IsNullOrWhiteSpace(candidate) || !File.Exists(candidate))
            return false;
        CommandResult result = RunCapture(
            candidate,
            "-c \"import sys; print('%d.%d' % sys.version_info[:2])\"",
            InstallDirectory
        );
        if (result.ExitCode != 0)
            return false;

        Version version;
        if (Version.TryParse(LastNonEmptyLine(result.Output), out version))
            return version.Major > 3 || (version.Major == 3 && version.Minor >= 11);
        return false;
    }

    private static string FindOnPath(string executable)
    {
        string path = Environment.GetEnvironmentVariable("PATH") ?? "";
        string[] folders = path.Split(Path.PathSeparator);
        foreach (string folder in folders)
        {
            if (String.IsNullOrWhiteSpace(folder))
                continue;
            string candidate = Path.Combine(folder.Trim(), executable);
            if (File.Exists(candidate))
                return candidate;
        }
        return null;
    }

    private static string LastNonEmptyLine(string value)
    {
        if (String.IsNullOrWhiteSpace(value))
            return "";
        string[] lines = value.Replace("\r", "").Split('\n');
        for (int i = lines.Length - 1; i >= 0; i--)
            if (!String.IsNullOrWhiteSpace(lines[i]))
                return lines[i].Trim();
        return "";
    }

    private static CommandResult RunCapture(string executable, string arguments, string workingDirectory)
    {
        ProcessStartInfo info = new ProcessStartInfo();
        info.FileName = executable;
        info.Arguments = arguments;
        info.WorkingDirectory = workingDirectory;
        info.UseShellExecute = false;
        info.CreateNoWindow = true;
        info.RedirectStandardOutput = true;
        info.RedirectStandardError = true;

        using (Process process = Process.Start(info))
        {
            string output = process.StandardOutput.ReadToEnd();
            string error = process.StandardError.ReadToEnd();
            process.WaitForExit();
            return new CommandResult {
                ExitCode = process.ExitCode,
                Output = output,
                Error = error
            };
        }
    }

    private static int RunAndWait(string executable, string arguments, string workingDirectory)
    {
        ProcessStartInfo info = new ProcessStartInfo();
        info.FileName = executable;
        info.Arguments = arguments;
        info.WorkingDirectory = workingDirectory;
        info.UseShellExecute = false;
        info.CreateNoWindow = false;
        using (Process process = Process.Start(info))
        {
            process.WaitForExit();
            return process.ExitCode;
        }
    }

    private static string Quote(string value)
    {
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }
}
