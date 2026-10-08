"""Explicit, capability-gated module boundary separate from title launching."""
import hashlib
import re
import secrets
import tempfile
import time
from pathlib import Path
from hash_registry import RegistryError, verify_digest
from diagnostics import BridgeDiagnostic

BETA_DIRECT_UNLOAD = False


def valid_module_name(name):
    return (isinstance(name, str) and 5 <= len(name) <= 128 and name.lower().endswith('.xex')
            and name.isascii() and all(' ' <= char <= '~' and char not in '\\/:*?"<>|' for char in name))


def listed_file(item, name):
    return (isinstance(item, dict) and isinstance(item.get('name'), str) and
            item['name'].rsplit('\\', 1)[-1].casefold() == name.casefold())


class NeighborhoodPluginAdapter:
    def __init__(self, bridge):
        self.bridge = bridge

    def stream_unload_ready(self):
        receiver = self.bridge.stream360
        return (receiver is not None and receiver.status()['safe_to_unload'] and
                self.bridge.target == receiver.expected_ip)

    def stage_companion(self, path, sha256, size):
        parent = path.rsplit('\\', 1)[0]
        name = 'NebulahCompanion-' + secrets.token_hex(8) + '.xex'
        runtime = parent + '\\' + name
        listing = self.bridge.adapter('browse', path=parent + '\\').get('files')
        if not isinstance(listing, list) or any(listed_file(item, name) for item in listing):
            raise ValueError('Temporary Companion path is unavailable.')
        with tempfile.TemporaryDirectory(prefix='nebulah-companion-') as folder:
            local = str(Path(folder) / 'companion.xex')
            self.bridge.adapter('download-file', path=path, local=local, size=size)
            if Path(local).stat().st_size != size or hashlib.sha256(Path(local).read_bytes()).hexdigest() != sha256:
                raise BridgeDiagnostic('MODULE_FILE_CHANGED', 'module')
            self.bridge.workspace().store.companion_run_add(self.bridge.target, runtime, sha256, size)
            self.bridge.adapter('upload-file', local=local, path=runtime, size=size)
        verified = self.bridge.adapter('verify-upload', path=runtime, size=size)
        if verified.get('sha256') != sha256:
            raise BridgeDiagnostic('MODULE_FILE_CHANGED', 'module')
        return runtime

    def cleanup_companion_runs(self):
        from server import safe_path
        store = self.bridge.workspace().store
        runs = store.companion_runs(self.bridge.target)
        if not runs:return {'removed': 0, 'pending': 0}
        modules = self.observed_modules()
        removed = 0
        for run in runs:
            try:
                path = safe_path(run['path'], self.bridge.drives)
                name = path.rsplit('\\', 1)[-1]
                if name.casefold() in modules:continue
                parent = path.rsplit('\\', 1)[0] + '\\'
                files = self.bridge.adapter('browse', path=parent).get('files')
                if not isinstance(files, list):continue
                if not any(listed_file(item, name) for item in files):
                    continue
                verified = self.bridge.adapter('verify-upload', path=path, size=run['size'])
                if verified.get('sha256') != run['sha256']:continue
                self.bridge.adapter('delete-file', path=path)
                after = self.bridge.adapter('browse', path=parent).get('files')
                if isinstance(after, list) and not any(listed_file(item, name) for item in after):
                    store.companion_run_remove(self.bridge.target, path)
                    removed += 1
            except (BridgeDiagnostic, ValueError, OSError):
                continue
        return {'removed': removed, 'pending': len(store.companion_runs(self.bridge.target))}

    def capabilities(self):
        from server import BETA_GATED_ACTIONS
        ready = False
        component = False
        force_release = False
        if self.bridge.target is not None:
            try: ready = self.bridge.adapter('plugin-probe').get('ready') is True
            except (ValueError, OSError): pass
            if ready:
                try:
                    probe = self.bridge.adapter('component-probe')
                    component = probe.get('ready') is True
                    force_release = component and probe.get('force_release') is True
                except (ValueError, OSError): pass
        return {'adapter': 'Neighborhood/JRPC2', 'connected': self.bridge.target is not None,
                'inspect': True, 'inventory': True, 'load': ready, 'unload': ready and (component or BETA_DIRECT_UNLOAD),
                'component': component, 'force_release': force_release and 'plugins/force-release' not in BETA_GATED_ACTIONS, 'component_capacity': 32 if component else 0,
                'slots': False, 'install': False,
                'reason': 'Nebulah XEX manager is available for tracked loads and unloads.' if component else
                          'JRPC2 loading available; direct unload is paused for console validation.' if ready else
                          'JRPC2 module control unavailable; load and unload are disabled.'}

    def unload_allowed(self, name):
        if not valid_module_name(name):
            return False
        if name.casefold() in self.bridge.plugin_unload_uncertain:
            return False
        managed = self.bridge.plugin_managed.get(name.casefold())
        if isinstance(managed, dict) and managed.get('route') == 'component':
            try:return self.bridge.adapter('component-state', name=name).get('state') == 1
            except (ValueError, OSError):return False
        if not BETA_DIRECT_UNLOAD:return False
        if name.casefold() == 'xbox360stream.xex':
            return self.stream_unload_ready()
        return name.casefold() in self.bridge.plugin_managed

    def observed_modules(self):
        inventory = self.bridge.adapter('plugins')
        modules = inventory.get('modules')
        if inventory.get('state') != 'observed' or not isinstance(modules, list):
            raise BridgeDiagnostic('MODULE_RUNTIME_UNAVAILABLE', 'module')
        return {item['name'].casefold() for item in modules
                if isinstance(item, dict) and isinstance(item.get('name'), str)}

    def assert_controller_inactive(self, name):
        if not re.fullmatch(r'NebulahCompanion(?:-[A-Za-z0-9_]+)?\.xex', name, re.I):
            return
        try:
            component = self.bridge.adapter('component-probe')
            if component.get('name', '').casefold() == name.casefold():
                if component.get('protocol') in (2, 3):
                    return
                if component.get('protocol') == 4 and self.bridge.adapter('component-input-probe').get('active') is False:
                    return
        except (BridgeDiagnostic, ValueError, OSError):
            pass
        raise ValueError('Companion controller state is active or unknown. Cold reboot before removing this module.')

    def dispatch(self, action, data):
        if action == 'plugins/capabilities':
            return self.capabilities()
        if action in ('plugins/install', 'plugins/slots'):
            raise ValueError('Plugin slots and installation are not available.')
        if self.bridge.target is None:
            raise ValueError('Connect a console first.')
        if action == 'plugins/managed-state':
            if set(data) != {'name'} or not valid_module_name(data['name']):
                raise ValueError('Choose one loaded module name.')
            if not self.capabilities()['component']:
                return {'state': 'unavailable'}
            observed = data['name'].casefold() in self.observed_modules()
            state = self.bridge.adapter('component-state', name=data['name']).get('state')
            if state not in (0, 1, 2, 3):raise ValueError('Nebulah manager state was invalid.')
            return {'state': 'managed' if observed and state == 1 else 'release-uncertain' if observed and state == 2 else 'force-uncertain' if state == 3 else 'not-managed'}
        if action == 'plugins/load':
            if set(data) - {'path', 'sha256', 'build_id', 'confirmed', 'route'} or data.get('confirmed') is not True:
                raise ValueError('Confirm the exact module path and measured SHA-256 before loading.')
            route = data.get('route', 'neighborhood')
            if route not in ('neighborhood', 'component'):raise ValueError('Choose a supported plugin route.')
            from server import safe_path
            path = safe_path(data.get('path'), self.bridge.drives)
            expected = data.get('sha256')
            if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', expected):
                raise ValueError('A measured SHA-256 is required.')
            if not path.isascii(): raise ValueError('JRPC2 module paths must use ASCII characters.')
            value = self.bridge.inspect(path, allow_module=True)
            if value.get('plugin') is not True or value.get('hash') != expected.lower():
                raise BridgeDiagnostic('MODULE_FILE_CHANGED', 'module')
            try: review = verify_digest(value['hash'], value['size'], data.get('build_id'))
            except (RegistryError, OSError): raise ValueError('Build registry unavailable; module loading paused.') from None
            if review['status'] in ('mismatch', 'revoked', 'unknown-build'):
                raise ValueError('Module differs from the selected build or has been revoked.')
            capability = self.capabilities()
            if not capability['load'] or (route == 'component' and not capability['component']):
                raise ValueError('JRPC2 module control unavailable on this console.')
            name = path.rsplit('\\', 1)[-1]
            observed = self.observed_modules()
            if name.casefold() in observed or (name.casefold() == 'nebulahcompanion.xex' and any(re.fullmatch(r'nebulahcompanion(?:-[a-z0-9_]+)?\.xex', item) for item in observed)):
                raise BridgeDiagnostic('MODULE_ALREADY_LOADED', 'module')
            runtime = self.stage_companion(path, value['hash'], value['size']) if name.casefold() == 'nebulahcompanion.xex' and route == 'neighborhood' else path
            runtime_name = runtime.rsplit('\\', 1)[-1]
            try:
                result = self.bridge.adapter('component-load' if route == 'component' else 'plugin-load', path=runtime, sha256=value['hash'], size=value['size'])
            except BridgeDiagnostic as error:
                if error.code == 'MODULE_LOAD_FAILED':
                    # A failed JRPC reply can precede the XBDM module-list update.
                    # Recheck only; never issue a second load to resolve ambiguity.
                    for attempt in range(5):
                        try: observed = runtime_name.casefold() in self.observed_modules()
                        except (BridgeDiagnostic, ValueError, OSError): observed = False
                        if observed:
                            raise BridgeDiagnostic('MODULE_LOAD_UNCONFIRMED', 'module',
                                                   error.architecture, error.hresult,
                                                   error.phase, error.module_status, error.path_mode) from None
                        if attempt < 4: time.sleep(0.5)
                raise
            if result.get('ok') is not True or result.get('name', '').casefold() != runtime_name.casefold():
                raise ValueError('Module load was not confirmed by the console.')
            runtime_path = result.get('runtime_path')
            alias = 'Usb:' + runtime[5:] if runtime.casefold().startswith('usb0:\\') else None
            if runtime_path != runtime and (alias is None or runtime_path != alias):
                raise ValueError('Module load path was not confirmed by the adapter.')
            path_mode = 'verified-usb-alias' if runtime_path == alias else 'selected-path'
            if result.get('path_mode') != path_mode:
                raise ValueError('Module load path mode was not confirmed by the adapter.')
            self.bridge.plugin_managed[runtime_name.casefold()] = {'path': path, 'runtime_path': runtime_path, 'sha256': value['hash'], 'route': route}
            if re.fullmatch(r'NebulahCompanion(?:-[A-Za-z0-9_]+)?\.xex', runtime_name, re.I):
                try:self.bridge.adapter('notify', message='Nebulah Companion module loaded')
                except (BridgeDiagnostic, ValueError, OSError):pass
            return {'name': runtime_name, 'state': 'loaded', 'sha256': value['hash'], 'review_status': review['status'],
                    'runtime_path': runtime_path, 'path_mode': path_mode, 'route': route}
        if action == 'plugins/unload':
            if set(data) - {'name', 'confirmed', 'route'} or data.get('confirmed') is not True or data.get('route', 'neighborhood') not in ('neighborhood', 'component'):
                raise ValueError('Confirm the exact loaded module name before unloading.')
            name = data['name']
            if not valid_module_name(name):raise ValueError('Choose one loaded module name.')
            self.assert_controller_inactive(name)
            route = data.get('route', 'neighborhood')
            if route == 'component':
                if name.casefold() in self.bridge.plugin_unload_uncertain or self.dispatch('plugins/managed-state', {'name': name})['state'] != 'managed':
                    raise ValueError('Only active Nebulah-managed modules may be unloaded once.')
            elif not self.unload_allowed(name) or not self.capabilities()['unload']:
                raise ValueError('Only eligible Nebulah-loaded modules may be unloaded. Refresh after an uncertain unload; Stream360 also requires SAFE_TO_UNLOAD.')
            if name.casefold() == 'xbox360stream.xex' and not self.stream_unload_ready():
                raise ValueError('Stream360 requires SAFE_TO_UNLOAD from this console before unloading.')
            try:
                result = self.bridge.adapter('component-unload' if route == 'component' else 'plugin-unload', name=name)
            except BridgeDiagnostic as error:
                if error.code == 'MODULE_UNLOAD_FAILED' and (error.phase == 'module-inventory' and error.module_status == '0x00000000' or route == 'component' and error.phase in ('module-result','module-inventory')):
                    # The kernel accepted one unload. Never repeat it while the
                    # module remains listed: its reference count or cleanup is unknown.
                    self.bridge.plugin_unload_uncertain.add(name.casefold())
                    self.bridge.plugin_unload_target=self.bridge.target
                raise
            if result.get('ok') is not True or result.get('name', '').casefold() != name.casefold():
                raise ValueError('Module unload was not confirmed by the console.')
            self.bridge.plugin_managed.pop(name.casefold(), None)
            if name.casefold() == 'xbox360stream.xex' and self.bridge.stream360 is not None:
                self.bridge.stream360.stop()
            return {'name': name, 'state': 'unloaded'}
        if action == 'plugins/force-release':
            if set(data) != {'name', 'confirmed'} or data['confirmed'] is not True or not valid_module_name(data['name']):
                raise ValueError('Confirm one exact module name before force release.')
            name = data['name']
            self.assert_controller_inactive(name)
            key = name.casefold()
            if (key not in self.bridge.plugin_unload_uncertain or key in self.bridge.plugin_force_attempted or
                    not self.capabilities()['force_release'] or
                    self.dispatch('plugins/managed-state', {'name': name})['state'] != 'release-uncertain'):
                raise ValueError('Force release requires one failed Nebulah-managed unload and the current manager.')
            if key == 'xbox360stream.xex':
                if not self.stream_unload_ready():
                    raise ValueError('Stream360 requires SAFE_TO_UNLOAD from this console before force release.')
            if key not in self.observed_modules():
                raise ValueError('Module is no longer listed; refresh inventory.')
            self.bridge.plugin_force_attempted.add(key)
            result = self.bridge.adapter('component-force-release', name=name)
            if result.get('ok') is not True or result.get('name', '').casefold() != key:
                raise ValueError('Forced release was not confirmed by the console.')
            self.bridge.plugin_managed.pop(key, None)
            self.bridge.plugin_unload_uncertain.discard(key)
            if key == 'xbox360stream.xex' and self.bridge.stream360 is not None:
                self.bridge.stream360.stop()
            return {'name': name, 'state': 'unloaded'}
        if action == 'plugins/library':
            listing = self.bridge.workspace().store.library(self.bridge.target)
            return {'files': [item for item in listing['files'] if (item.get('inspection') or {}).get('plugin') is True]}
        if action == 'plugins/forget':
            if set(data) != {'path', 'sha256'}:
                raise ValueError('Choose one inspected plugin entry to remove.')
            from server import safe_path
            raw_path = data.get('path')
            root = re.match(r'[A-Za-z0-9_]+:\\', raw_path) if isinstance(raw_path, str) else None
            if root is None:
                raise ValueError('Choose an absolute inspected plugin path.')
            path = safe_path(raw_path, [root.group(0)])
            digest = data.get('sha256')
            if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', digest):
                raise ValueError('Choose the measured inspection to remove.')
            return self.bridge.workspace().store.remove_inspected_plugin(self.bridge.target, path, digest.lower())
        if action != 'plugins/inspect':
            raise ValueError('Unknown plugin adapter operation.')
        from server import safe_path
        if set(data) - {'path', 'build_id'}:
            raise ValueError('Only a plugin path and optional reviewed build may be supplied.')
        path = safe_path(data.get('path'), self.bridge.drives)
        value = self.bridge.inspect(path, allow_module=True)
        if not value.get('valid') or value.get('plugin') is not True:
            raise ValueError('This XEX is not structurally marked as a DLL/plugin. Use Games for title launches.')
        try:
            review = verify_digest(value['hash'], value['size'], data.get('build_id'))
        except (RegistryError, OSError):
            review = {'status': 'registry-error', 'discrepancies': ['Build registry unavailable.']}
        # Inspection records measured bytes but cannot authorize execution or installation.
        self.bridge.workspace().store.record_inspection(self.bridge.target, path, value)
        return {'path': path, 'plugin': True, 'sha256': value['hash'], 'size': value['size'],
                'review_status': review['status'], 'discrepancies': review.get('discrepancies', []),
                'runtime_available': self.capabilities()['load'], 'install_available': False,
                'note': 'Structural inspection is not signature verification or console compatibility.'}
