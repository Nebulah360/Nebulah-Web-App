// Read-only COM type-information probe. These are the first two standard
// IDispatch slots, not an SDK implementation or a console-operation interface.
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using T = System.Runtime.InteropServices.ComTypes;
namespace NebulahDiagnostics {
    [ComImport, Guid("00020400-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface AutomationMetadata {
        [PreserveSig] int GetTypeInfoCount(out uint count);
        [PreserveSig] int GetTypeInfo(uint index, uint locale, out T.ITypeInfo info);
    }
    // Query the already verified console IID, then use only its standard
    // inherited IDispatch metadata slots. No console methods are called here.
    [ComImport, Guid("75DD80A9-5A33-42D4-8A39-AB07C9B17CC3"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface ConsoleMetadata {
        [PreserveSig] int GetTypeInfoCount(out uint count);
        [PreserveSig] int GetTypeInfo(uint index, uint locale, out T.ITypeInfo info);
    }
    public static class Probe {
        static readonly HashSet<string> Members = new HashSet<string>(StringComparer.OrdinalIgnoreCase) {
            "OpenConnection", "CloseConnection", "SendTextCommand", "ReceiveSocketLine",
            "ConnectTimeout", "ConversationTimeout", "Drives", "ConsoleType",
            "DebugTarget", "RunningProcessInfo", "OpenConsole", "DefaultConsole"
        };
        static void Release(object value) { if (value != null && Marshal.IsComObject(value)) Marshal.ReleaseComObject(value); }
        static string Name(string value) {
            if (String.IsNullOrEmpty(value) || value.Length > 100) return "unrecognized";
            foreach(char c in value) if (!Char.IsLetterOrDigit(c) && c!='_' && c!='.') return "unrecognized";
            return value;
        }
        static void Describe(T.ITypeInfo info, List<string> lines, HashSet<string> visited, int depth) {
            if (depth > 4) return;
            IntPtr attrPointer=IntPtr.Zero;
            try {
                info.GetTypeAttr(out attrPointer);
                var attr=(T.TYPEATTR)Marshal.PtrToStructure(attrPointer,typeof(T.TYPEATTR));
                string identity=attr.guid.ToString()+":"+attr.typekind;
                if(!visited.Add(identity)) return;
                string name,doc,help; int context;
                info.GetDocumentation(-1,out name,out doc,out context,out help);
                lines.Add("Type: "+Name(name)+"; IID: "+attr.guid+"; kind: "+attr.typekind+"; functions: "+attr.cFuncs);
                for(int i=0;i<Math.Min((int)attr.cFuncs,512);i++) {
                    IntPtr pointer=IntPtr.Zero;
                    try {
                        info.GetFuncDesc(i,out pointer);
                        var function=(T.FUNCDESC)Marshal.PtrToStructure(pointer,typeof(T.FUNCDESC));
                        info.GetDocumentation(function.memid,out name,out doc,out context,out help);
                        if(Members.Contains(name)) lines.Add("  Member: "+name+"; ID: "+function.memid+"; kind: "+function.invkind+"; parameters: "+function.cParams);
                    } finally { if(pointer!=IntPtr.Zero) info.ReleaseFuncDesc(pointer); }
                }
                for(int i=0;i<Math.Min((int)attr.cImplTypes,8);i++) {
                    T.ITypeInfo inherited=null;
                    try { int reference; info.GetRefTypeOfImplType(i,out reference); info.GetRefTypeInfo(reference,out inherited); Describe(inherited,lines,visited,depth+1); }
                    catch(COMException e) { lines.Add("Inherited metadata HRESULT: 0x"+e.HResult.ToString("X8")); }
                    finally { Release(inherited); }
                }
            } finally { if(attrPointer!=IntPtr.Zero) info.ReleaseTypeAttr(attrPointer); }
        }
        public static string[] Read(object target, bool consoleView) {
            var lines=new List<string>(); T.ITypeInfo info=null;
            try {
                uint count; int hr;
                if(consoleView) {
                    var view=(ConsoleMetadata)target;
                    hr=view.GetTypeInfoCount(out count); Marshal.ThrowExceptionForHR(hr);
                    lines.Add("Console view type-info count: "+count);
                    if(count==0) return lines.ToArray();
                    hr=view.GetTypeInfo(0,0,out info);
                } else {
                    var view=(AutomationMetadata)target;
                    hr=view.GetTypeInfoCount(out count); Marshal.ThrowExceptionForHR(hr);
                    lines.Add("Default Automation type-info count: "+count);
                    if(count==0) return lines.ToArray();
                    hr=view.GetTypeInfo(0,0,out info);
                }
                Marshal.ThrowExceptionForHR(hr);
                Describe(info,lines,new HashSet<string>(),0);
            } catch(Exception e) { lines.Add("Metadata failure: "+e.GetType().Name+"; HRESULT: 0x"+e.HResult.ToString("X8")); }
            finally { Release(info); }
            return lines.ToArray();
        }
    }
}
