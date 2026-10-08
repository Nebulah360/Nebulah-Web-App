// Original late-binding bridge. Uses the user's registered COM server; no SDK
// assemblies or binaries are redistributed. The minimal dispatch contract below
// selects the console IID explicitly; it is not a vtable-layout declaration.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;

namespace Nebulah {
    public static class ChunkReadFallback {
        // Some installed XDevkit versions fail SAFEARRAY chunk reads with E_UNEXPECTED.
        // Use the established whole-file API only for that failure; never skip verification.
        public static byte[] Read(Func<byte[]> nativeRead, Func<long> size, Action<string> receive,
                                  uint offset, uint count) {
            if (count > 65536) throw new InvalidOperationException("Chunk unavailable");
            try { return nativeRead(); }
            catch (COMException error) {
                if (error.ErrorCode != unchecked((int)0x8000FFFF)) throw;
            }
            const long limit = 128L * 1024 * 1024;
            long expected = size();
            if (expected < 0 || expected > limit || (long)offset + count > expected)
                throw new InvalidOperationException("Fallback file outside limits");
            string local = Path.GetTempFileName();
            try {
                receive(local);
                using (var file = new FileStream(local, FileMode.Open, FileAccess.Read, FileShare.Read)) {
                    if (file.Length != expected || file.Length > limit)
                        throw new InvalidOperationException("Fallback file changed");
                    file.Position = offset;
                    var result = new byte[count];
                    int done = 0;
                    while (done < result.Length) {
                        int got = file.Read(result, done, result.Length - done);
                        if (got == 0) throw new InvalidOperationException("Fallback short read");
                        done += got;
                    }
                    return result;
                }
            } finally { File.Delete(local); }
        }
    }
    // InterfaceIsIDispatch makes the CLR invoke these DISPIDs on this IID.
    // Default IDispatch can be IXboxDebugTarget on the SAME COM identity.
    [ComImport, Guid("75DD80A9-5A33-42D4-8A39-AB07C9B17CC3")]
    [InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
    public interface IConsoleAutomation {
        [DispId(21)] uint ConnectTimeout { set; }
        [DispId(22)] uint ConversationTimeout { set; }
        [DispId(120)] string Drives { get; }
        [DispId(170)] object ConsoleType { get; }
        [DispId(102)] object RunningProcessInfo { get; }
        [DispId(51)] object DebugTarget { get; }
        [DispId(110)] uint OpenConnection([MarshalAs(UnmanagedType.BStr)] string handler);
        [DispId(111)] void CloseConnection(uint connection);
        [DispId(112)] void SendTextCommand(uint connection, [MarshalAs(UnmanagedType.BStr)] string command,
            [Out, MarshalAs(UnmanagedType.BStr)] out string response);
        [DispId(113)] void ReceiveSocketLine(uint connection, [Out, MarshalAs(UnmanagedType.BStr)] out string line);
        [DispId(127)] object DirectoryFiles([MarshalAs(UnmanagedType.BStr)] string path);
        [DispId(140)] object GetFileObject([MarshalAs(UnmanagedType.BStr)] string path);
        [DispId(131)] void ReceiveFile([MarshalAs(UnmanagedType.BStr)] string local, [MarshalAs(UnmanagedType.BStr)] string remote);
        [DispId(130)] void SendFile([MarshalAs(UnmanagedType.BStr)] string local, [MarshalAs(UnmanagedType.BStr)] string remote);
        [DispId(132)] void ReadFileBytes([MarshalAs(UnmanagedType.BStr)] string path, uint offset, uint count,
            [In, Out, MarshalAs(UnmanagedType.SafeArray, SafeArraySubType=VarEnum.VT_UI1)] byte[] data, out uint read);
        [DispId(141)] void RenameFile([MarshalAs(UnmanagedType.BStr)] string oldName, [MarshalAs(UnmanagedType.BStr)] string newName);
        [DispId(142)] void DeleteFile([MarshalAs(UnmanagedType.BStr)] string path);
        [DispId(100)] void Reboot([MarshalAs(UnmanagedType.BStr)] string path,
            [MarshalAs(UnmanagedType.BStr)] string directory, [MarshalAs(UnmanagedType.BStr)] string arguments, uint flags);
    }
    [ComImport, Guid("DFCF3F84-5394-448D-BCAC-E30AF6C840E1")]
    [InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
    public interface IFilesAutomation {
        [DispId(1)] int Count { get; }
        [DispId(0)] object this[int index] { get; }
    }
    [ComImport, Guid("B9DBC76D-8A06-4EEB-84BD-1AD42F0AFE28")]
    [InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
    public interface IFileAutomation {
        [DispId(0)] string Name { get; }
        [DispId(3)] ulong Size { get; }
        [DispId(5)] bool IsDirectory { get; }
    }
    public static class Dispatch {
        // Numeric IDispatch invocation bypasses GetIDsOfNames. Managed fixtures
        // retain ordinary reflection; they are not COM integration tests.
        public static string MemberName(bool isCom, string name, int dispatchId) {
            return isCom ? "[DispID=" + dispatchId.ToString(CultureInfo.InvariantCulture) + "]" : name;
        }
        public static string RecordText(object record, string name) {
            if (record == null) return null;
            var field = record.GetType().GetField(name);
            if (field != null) return Convert.ToString(field.GetValue(record));
            var property = record.GetType().GetProperty(name);
            if (property != null) return Convert.ToString(property.GetValue(record, null));
            throw new MissingMemberException("Record field unavailable");
        }
        public static object Call(object target, string name, int dispatchId, object[] args, int outputIndex) {
            ParameterModifier[] modifiers = null;
            if (outputIndex >= 0) {
                var modifier = new ParameterModifier(args.Length);
                modifier[outputIndex] = true;
                modifiers = new [] { modifier };
            }
            return target.GetType().InvokeMember(MemberName(Marshal.IsComObject(target), name, dispatchId),
                BindingFlags.Public | BindingFlags.Instance | BindingFlags.InvokeMethod,
                null, target, args, modifiers, CultureInfo.InvariantCulture, null);
        }
        public static object Get(object target, string name, int dispatchId, params object[] args) {
            return target.GetType().InvokeMember(MemberName(Marshal.IsComObject(target), name, dispatchId),
                BindingFlags.Public | BindingFlags.Instance | BindingFlags.GetProperty,
                null, target, args, CultureInfo.InvariantCulture);
        }
        public static void Set(object target, string name, int dispatchId, object value) {
            target.GetType().InvokeMember(MemberName(Marshal.IsComObject(target), name, dispatchId),
                BindingFlags.Public | BindingFlags.Instance | BindingFlags.SetProperty,
                null, target, new [] { value }, CultureInfo.InvariantCulture);
        }
        public static void Release(object value) {
            if (value != null && Marshal.IsComObject(value)) Marshal.ReleaseComObject(value);
        }
    }
    public sealed class FileInfo {
        public string Name { get; set; }
        public bool IsDirectory { get; set; }
        public long Size { get; set; }
        internal static FileInfo Read(object file) {
            try {
                if (Marshal.IsComObject(file)) {
                    var entry = (IFileAutomation)file;
                    return new FileInfo { Name = entry.Name, IsDirectory = entry.IsDirectory, Size = checked((long)entry.Size) };
                }
                return new FileInfo {
                Name = Convert.ToString(Dispatch.Get(file, "Name", 0)),
                IsDirectory = Convert.ToBoolean(Dispatch.Get(file, "IsDirectory", 5)),
                Size = Convert.ToInt64(Dispatch.Get(file, "Size", 3))
            }; } finally { Dispatch.Release(file); }
        }
    }
    public sealed class ModuleInfo { public string Name { get; set; } }
    public sealed class ProcessInfo { public string ProgramName { get; set; } }
    public sealed class DebugInfo { public ModuleInfo[] Modules { get; set; } }
    public sealed class ConsoleDispatch {
        private readonly object native;
        private readonly IConsoleAutomation console;
        public ConsoleDispatch(object nativeObject) {
            if (nativeObject == null) throw new ArgumentNullException("nativeObject");
            if (Marshal.IsComObject(nativeObject)) {
                IntPtr unknown = IntPtr.Zero, consoleInterface = IntPtr.Zero;
                try {
                    unknown = Marshal.GetIUnknownForObject(nativeObject);
                    Guid iid = new Guid("75DD80A9-5A33-42D4-8A39-AB07C9B17CC3");
                    Marshal.ThrowExceptionForHR(Marshal.QueryInterface(unknown, ref iid, out consoleInterface));
                } finally {
                    if (consoleInterface != IntPtr.Zero) Marshal.Release(consoleInterface);
                    if (unknown != IntPtr.Zero) Marshal.Release(unknown);
                }
            }
            native = nativeObject;
            if (Marshal.IsComObject(nativeObject)) console = (IConsoleAutomation)nativeObject;
        }
        public uint ConnectTimeout { set { if (console != null) console.ConnectTimeout = value; else Dispatch.Set(native, "ConnectTimeout", 21, value); } }
        public uint ConversationTimeout { set { if (console != null) console.ConversationTimeout = value; else Dispatch.Set(native, "ConversationTimeout", 22, value); } }
        public string Drives { get { return console != null ? console.Drives : Convert.ToString(Dispatch.Get(native, "Drives", 120)); } }
        public object ConsoleType { get { return console != null ? console.ConsoleType : Dispatch.Get(native, "ConsoleType", 170); } }
        public uint OpenConnection(string handler) {
            if (console != null) return console.OpenConnection(String.IsNullOrEmpty(handler) ? null : handler);
            return Convert.ToUInt32(Dispatch.Call(native, "OpenConnection", 110, new object[] { String.IsNullOrEmpty(handler) ? null : handler }, -1));
        }
        public void CloseConnection(uint connection) {
            if (console != null) { console.CloseConnection(connection); return; }
            Dispatch.Call(native, "CloseConnection", 111, new object[] { connection }, -1);
        }
        public void SendTextCommand(uint connection, string command, out string response) {
            if (console != null) { console.SendTextCommand(connection, command, out response); return; }
            object[] args = { connection, command, null };
            Dispatch.Call(native, "SendTextCommand", 112, args, 2);
            response = Convert.ToString(args[2]);
        }
        public void ReceiveSocketLine(uint connection, out string line) {
            if (console != null) { console.ReceiveSocketLine(connection, out line); return; }
            object[] args = { connection, null };
            Dispatch.Call(native, "ReceiveSocketLine", 113, args, 1);
            line = Convert.ToString(args[1]);
        }
        public ProcessInfo RunningProcessInfo { get {
            object info = console != null ? console.RunningProcessInfo : Dispatch.Get(native, "RunningProcessInfo", 102);
            try {
                // SDK process records can marshal as a managed value type.
                return new ProcessInfo { ProgramName = Dispatch.RecordText(info, "ProgramName") };
            } finally { Dispatch.Release(info); }
        } }
        public DebugInfo DebugTarget { get {
            object debug = console != null ? console.DebugTarget : Dispatch.Get(native, "DebugTarget", 51), modules = null;
            try {
                modules = Dispatch.Get(debug, "Modules", 100);
                int count = Convert.ToInt32(Dispatch.Get(modules, "Count", 1));
                if (count < 0 || count > 4096) throw new InvalidOperationException("Invalid module count");
                var result = new List<ModuleInfo>();
                for (int i = 0; i < count; i++) {
                    object module = Dispatch.Get(modules, "Item", 0, i);
                    object record = null;
                    try {
                        record = Dispatch.Get(module, "ModuleInfo", 0);
                        result.Add(new ModuleInfo { Name = Dispatch.RecordText(record, "Name") });
                    } finally { Dispatch.Release(record); Dispatch.Release(module); }
                }
                return new DebugInfo { Modules = result.ToArray() };
            } finally { Dispatch.Release(modules); Dispatch.Release(debug); }
        } }
        public FileInfo[] DirectoryFiles(string path) {
            object files = console != null ? console.DirectoryFiles(path) : Dispatch.Call(native, "DirectoryFiles", 127, new object[] { path }, -1);
            try {
                var collection = Marshal.IsComObject(files) ? (IFilesAutomation)files : null;
                int count = collection != null ? collection.Count : Convert.ToInt32(Dispatch.Get(files, "Count", 1));
                if (count < 0 || count > 100000) throw new InvalidOperationException("Invalid file count");
                var result = new List<FileInfo>();
                for (int i = 0; i < count; i++) result.Add(FileInfo.Read(collection != null ? collection[i] : Dispatch.Get(files, "Item", 0, i)));
                return result.ToArray();
            } finally { Dispatch.Release(files); }
        }
        public bool DirectoryExists(string path) {
            object file = console != null ? console.GetFileObject(path) : Dispatch.Call(native, "GetFileObject", 140, new object[] { path }, -1);
            try {
                return Marshal.IsComObject(file) ? ((IFileAutomation)file).IsDirectory : Convert.ToBoolean(Dispatch.Get(file, "IsDirectory", 5));
            } finally { Dispatch.Release(file); }
        }
        public FileInfo GetFileObject(string path) {
            return FileInfo.Read(console != null ? console.GetFileObject(path) : Dispatch.Call(native, "GetFileObject", 140, new object[] { path }, -1));
        }
        public FileInfo GetDownloadFileInfo(string path) {
            int separator = path.LastIndexOf('\\');
            if (separator < 0 || separator == path.Length - 1)
                throw new ArgumentException("File path required", "path");
            string directory = path.Substring(0, separator + 1);
            string name = path.Substring(separator + 1);
            try {
                foreach (FileInfo file in DirectoryFiles(directory)) {
                    if (string.Equals(file.Name, name, StringComparison.OrdinalIgnoreCase) ||
                        string.Equals(file.Name, path, StringComparison.OrdinalIgnoreCase)) return file;
                }
            } catch (Exception) { }
            return GetFileObject(path);
        }
        public void ReceiveFile(string local, string remote) {
            if (console != null) { console.ReceiveFile(local, remote); return; }
            Dispatch.Call(native, "ReceiveFile", 131, new object[] { local, remote }, -1);
        }
        public byte[] ReadChunk(string path, uint offset, uint count) {
            if (console == null || count > 65536) throw new InvalidOperationException("Chunk unavailable");
            return ChunkReadFallback.Read(delegate {
                var data = new byte[count]; uint read;
                console.ReadFileBytes(path, offset, count, data, out read);
                if (read > count) throw new InvalidOperationException("Invalid read size");
                Array.Resize(ref data, checked((int)read)); return data;
            }, delegate { return GetFileObject(path).Size; },
               delegate(string local) { ReceiveFile(local, path); }, offset, count);
        }
        public void SendFile(string local, string remote) {
            if (console == null) throw new InvalidOperationException("COM required");
            console.SendFile(local, remote);
        }
        public void RenameFile(string oldName, string newName) {
            if (console == null) throw new InvalidOperationException("COM required");
            console.RenameFile(oldName, newName);
        }
        public void DeleteFile(string path) {
            if (console == null) throw new InvalidOperationException("COM required");
            console.DeleteFile(path);
        }
        public void Reboot(string path, string directory, string arguments, uint flags) {
            if (console != null) { console.Reboot(path, directory, arguments, flags); return; }
            Dispatch.Call(native, "Reboot", 100, new object[] { path, directory, arguments, flags }, -1);
        }
    }
}
