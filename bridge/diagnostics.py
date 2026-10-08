"""Allowlisted connection diagnostics. Never return raw COM/process output."""
import re
import json
from functools import lru_cache
from runtime_paths import ROOT

@lru_cache(maxsize=1)
def support_catalog():
    try:return json.loads((ROOT/"support/errors.json").read_text(encoding="utf-8"))["errors"]
    except (OSError,ValueError,KeyError):return {}

ERRORS = {
    'PLATFORM_UNSUPPORTED': ('Xbox connection needs Windows', 'Xbox 360 Neighborhood is available only through Windows COM.', 'Run Nebulah Link on Windows with licensed Neighborhood. macOS/Linux can open the local browser and keep saved data, but cannot connect to the Xbox.'),
    'RECOVERY_REQUIRED': ('Console recovery required', 'Console operations are paused after an uncertain adapter or transfer failure.', 'Check the console locally and restart it if frozen. Use Connect console and explicitly confirm recovery. Do not repeat network-interruption testing.'),
    'TRANSFER_CREATE_FAILED': ('Upload creation failed', 'Neighborhood SendFile could not send the staged upload to its partial filename.', 'Keep any partial and report this code and HRESULT. Confirm console recovery before reconnecting; sending may have started.'),
    'TRANSFER_APPEND_FAILED': ('Upload append failed', 'Neighborhood could not append a later upload chunk, including any applicable compatibility fallback.', 'Keep the partial file and report this code, HRESULT and byte offset.'),
    'TRANSFER_WRITE_FAILED': ('Upload write failed', 'Neighborhood could not create or write the upload partial file.', 'Keep the partial file and report this code and HRESULT. Do not change plugin settings based on this error.'),
    'TRANSFER_READBACK_FAILED': ('Upload read-back failed', 'The upload write returned, but Neighborhood could not read back the complete uploaded file for verification.', 'Keep the partial file and report this code and HRESULT. The upload has not been finalized.'),
    'TRANSFER_HASH_FAILED': ('Upload hash failed', 'The bridge could not hash the read-back bytes.', 'Update the bridge and report this code and HRESULT if the error repeats.'),
    'TRANSFER_READ_FAILED': ('Console file read failed', 'Neighborhood ReceiveFile could not copy the requested console file to the bridge.', 'Report this code and HRESULT and whether the file opens in Neighborhood.'),
    'TRANSFER_INFO_FAILED': ('Console file metadata unavailable', 'Neighborhood could not read metadata for the selected console file.', 'Refresh the file picker. Check whether that exact file opens in Neighborhood, then retry.'),
    'TRANSFER_RENAME_FAILED': ('Upload finalize failed', 'Neighborhood could not rename the verified partial file to its destination.', 'Keep the partial file and report this code and HRESULT. Do not assume the destination was finalized.'),
    'TRANSFER_CLEANUP_FAILED': ('Partial cleanup failed', 'Neighborhood could not remove the selected failed-upload partial file.', 'Keep the partial path. Confirm the console is responsive, then retry cleanup once or remove that exact .part file in Neighborhood.'),
    'STORAGE_LIST_INVALID': ('Directory entries could not be displayed', 'Neighborhood returned directory data that could not be safely normalized. This is not an empty-folder result.', 'Update the bridge and frontend together. Run tools/diagnose-neighborhood.ps1 and share the storage counts and failure codes; no file contents are required.'),
    'STORAGE_BROWSE_FAILED': ('Storage folder could not be read', 'Neighborhood could not enumerate the selected directory or read its file records.', 'Refresh console status to rediscover drives, select a storage root and retry Browse. Check whether the same folder opens in Neighborhood. Use adapter 7 or newer for explicit file-collection binding.'),
    'XDEVKIT_INTERFACE_FAILED': ('XDevkit interface adapter failed', 'The installed COM object opened, but the explicit dispatch wrapper could not be initialized.', 'Update all bridge files together, including ComDispatch.cs. Use Windows PowerShell 5.1 matching the installed Neighborhood architecture.'),
    'POWERSHELL_NOT_FOUND': ('PowerShell could not be started', 'The configured Windows PowerShell executable was not found.', 'Run the bridge on Windows. Check the --powershell path; the default uses 32-bit Windows PowerShell for Neighborhood.'),
    'POWERSHELL_START_FAILED': ('PowerShell startup failed', 'Windows could not start the Neighborhood adapter process.', 'Check permission to run Windows PowerShell and the configured executable path.'),
    'POWERSHELL_POLICY': ('PowerShell script execution blocked', 'PowerShell reported a script-execution policy or authorization error.', 'Unblock the downloaded project files in Windows file Properties. If this PC has a managed policy, ask its administrator to allow the adapter script.'),
    'XDEVKIT_COM_FAILED': ('XDevkit could not be loaded', 'The adapter could not activate XboxManager using its ProgID or registered COM class.', 'Neighborhood can work while COM registration is missing in this PowerShell architecture. Check or repair the installed Neighborhood/XDevkit COM registration. Compare 32-bit and 64-bit Windows PowerShell.'),
    'DEFAULT_CONSOLE_FAILED': ('Default console could not be read', 'XDevkit could not read its configured default console.', 'Run the bridge under the same Windows account as Neighborhood. Try entering the console IP explicitly in Connect console.'),
    'DEFAULT_CONSOLE_EMPTY': ('No default console returned', 'XDevkit returned an empty default-console setting for this Windows account.', 'Set the default in Neighborhood under the same Windows account, or enter the console IP explicitly in Connect console.'),
    'CONSOLE_OPEN_FAILED': ('Console could not be opened', 'XDevkit failed while opening the selected console.', 'Confirm Neighborhood can browse this console from the bridge PC. Try the console IP explicitly and check PC-to-console connectivity. This error alone does not prove a DashLaunch plugin problem.'),
    'STORAGE_DISCOVERY_FAILED': ('Console storage could not be read', 'The console object opened, but Neighborhood drive enumeration failed.', 'Try opening the drives in Neighborhood from the same PC/account. Check XDevkit adapter compatibility; a listed default console alone does not verify drive access.'),
    'ADAPTER_TIMEOUT': ('Neighborhood request timed out', 'The adapter exceeded its time limit (40 seconds normally; 210 seconds for bulk upload, download or verification).', 'Console operations are paused. The process deadline may have terminated an active call; check console recovery before explicitly reconnecting.'),
    'ADAPTER_RESPONSE_INVALID': ('Adapter returned an invalid response', 'The bridge could not decode the adapter response.', 'Update all project files together and restart the bridge. Verify the Windows PowerShell/XDevkit installation.'),
    'ADAPTER_OPERATION_FAILED': ('Neighborhood operation failed', 'The adapter failed after opening the console.', 'Check the selected console and operation, then retry. No raw exception text is exposed.'),
    'MODULE_RUNTIME_UNAVAILABLE': ('Module control unavailable', 'JRPC2 module calls or loaded-module inventory did not pass the capability probe.', 'Check that JRPC2 is loaded and responding, then refresh Plugin workspace.'),
    'MODULE_FILE_CHANGED': ('Module file changed', 'The selected XEX no longer matches its saved inspection or is not a DLL/plugin.', 'Inspect the current file, review its new SHA-256 and approve that exact file before loading.'),
    'MODULE_LOAD_FAILED': ('Module load failed', 'The console did not confirm the DLL/plugin module load.', 'Check the exact file and current module list. Reinspect the file before retrying.'),
    'MODULE_ALREADY_LOADED': ('Module already loaded', 'The selected module name already appears in the console module list. No load command was sent.', 'Check the running module list and receiver. Unload safely or cold reboot before another load attempt.'),
    'MODULE_LOAD_UNCONFIRMED': ('Module load outcome uncertain', 'The module appeared in the console list after an unconfirmed load reply.', 'Do not load it again. Check the receiver and console, then use the module safe-unload procedure if needed.'),
    'MODULE_UNLOAD_FAILED': ('Module unload failed', 'The console did not confirm the module was removed.', 'Check the module list and console responsiveness. For 360Stream, prepare unload and wait for SAFE_TO_UNLOAD.'),
    'CONSOLE_NOTIFY_FAILED': ('Xbox notification unconfirmed', 'JRPC2 did not confirm the notification command.', 'Check that JRPC2 is loaded and responding, then retry one test notification.'),
    'CONSOLE_POWER_FAILED': ('Console power command unconfirmed', 'Neighborhood did not confirm the requested reboot or shutdown command.', 'Check the console locally before retrying. The command may have started before the connection closed.'),
    'LAUNCH_INI_SAVE_FAILED': ('Plugin slot save unconfirmed', 'Neighborhood could not confirm the active launch.ini update.', 'Open the active launch.ini in Neighborhood. Check for a Nebulah .bak or .new recovery copy before retrying or rebooting.'),
    'ADAPTER_PROCESS_FAILED': ('Neighborhood adapter stopped', 'PowerShell exited without a recognized diagnostic.', 'Check script permission and the Windows PowerShell/XDevkit installation. Update all project files together and restart the bridge.'),
}
STAGES = {'startup','com','default-console','open-console','storage','operation','interface','module','power','launch-ini','transfer-info','transfer-create','transfer-append','transfer-write','transfer-readback','transfer-hash','transfer-read','transfer-rename','transfer-cleanup'}
MODULE_PHASES = {'module-path','module-probe','module-file','module-handle','module-resolve','module-call','module-result','module-inventory'}

class BridgeDiagnostic(ValueError):
    def __init__(self, code, stage='startup', architecture=None, hresult=None, phase=None, module_status=None, path_mode=None):
        self.code = code if isinstance(code,str) and code in ERRORS else 'ADAPTER_PROCESS_FAILED'
        self.stage = stage if isinstance(stage,str) and stage in STAGES else 'startup'
        self.architecture = architecture if architecture in ('x86','x64') else None
        self.hresult = hresult if isinstance(hresult,str) and re.fullmatch(r'0x[0-9A-Fa-f]{8}',hresult) else None
        self.phase = phase if isinstance(phase,str) and phase in MODULE_PHASES else None
        status_phase = self.phase == 'module-result' or (self.code == 'MODULE_UNLOAD_FAILED' and self.phase == 'module-inventory')
        self.module_status = module_status if status_phase and isinstance(module_status,str) and re.fullmatch(r'0x[0-9A-Fa-f]{8}',module_status) else None
        self.path_mode = path_mode if path_mode in ('selected-path', 'verified-usb-alias') else None
        self.title, self.reason, self.hint = ERRORS[self.code]
        entry=support_catalog().get(self.code,{})
        self.support_code=entry.get('support_code',self.code)
        self.reason=entry.get('message',self.reason)
        self.hint=entry.get('next_step',self.hint)
        if self.code == 'MODULE_LOAD_FAILED' and self.module_status == '0xC0000034':
            self.reason='The console could not find a required name during module loading.'
            self.hint=('The Usb: alias matched the selected file; check the XEX dependencies and console loader state before another attempt.'
                       if self.path_mode == 'verified-usb-alias' else
                       'Check the selected XEX, its dependencies and Module path mode. For USB, a verified Usb: alias may be available; the console loader can use a different path namespace than Neighborhood.')
        if self.code == 'MODULE_LOAD_FAILED' and self.module_status == '0xC0000018':
            self.title='Module address conflict'
            self.reason='The module loader reported a memory-address conflict.'
            self.hint='Refresh loaded modules before any retry. If this module is listed, check its receiver or output; do not load another copy.'
        if self.code == 'MODULE_UNLOAD_FAILED' and self.phase == 'module-probe':
            self.reason='The console module controls were unavailable before unload started.'
            self.hint='Wait for the console to finish booting, reconnect, and refresh the module list. No unload call was confirmed.'
        if self.code == 'MODULE_UNLOAD_FAILED' and self.phase == 'module-inventory' and self.module_status == '0x00000000':
            self.title='Module unload outcome uncertain'
            self.reason='The unload call returned success, but the module was still listed during the confirmation window.'
            self.hint='Refresh the module list after the console settles. Do not send another unload while the first call may still be completing.'
        super().__init__(self.reason)

    def payload(self):
        return {'error':self.reason, 'diagnostic':{'code':self.code,'support_code':self.support_code,'title':self.title,'stage':self.stage,'phase':self.phase,'module_status':self.module_status,'path_mode':self.path_mode,'reason':self.reason,'hint':self.hint,'architecture':self.architecture,'hresult':self.hresult}}
