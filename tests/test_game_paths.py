import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_bridge import Fake
from game_paths import GamePaths

class GameShortcuts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'games.db'
        self.store=GamePaths(self.path)
        self.patch=patch('server.GamePaths',lambda:self.store)
        self.patch.start();self.addCleanup(self.patch.stop)
        self.bridge=Fake()
        self.bridge.adapter=lambda action,**kw:{'files':[{'name':'default.xex','size':500}]}

    def save(self,**changes):
        data={'name':'My game','folder':'Test:\\Games\\','executable':'default.xex'}
        data.update(changes)
        return self.bridge.dispatch('games/save',data)

    def test_persistence_and_target_isolation(self):
        self.save()
        entries=GamePaths(self.path).list('DEMO')
        self.assertEqual(entries[0]['folder'],'Test:\\Games\\')
        self.assertEqual(self.store.list('other'),[])
        self.store.remove('other',entries[0]['id'])
        self.assertEqual(len(self.store.list('demo')),1)
        self.save(name='Renamed')
        self.assertEqual(len(self.store.list('demo')),1)
        self.assertEqual(self.store.list('demo')[0]['name'],'Renamed')
        self.store.remove('demo',entries[0]['id'])
        self.assertEqual(self.store.list('demo'),[])

    def test_rejects_invalid_paths_and_missing_xex(self):
        for changes in [{'folder':'Other:\\Game\\'},{'folder':'Test:\\..\\'}, {'executable':'..\\default.xex'}, {'executable':'missing.xex'}, {'executable':'plugin.dll'}, {'name':'\n'}]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.save(**changes)
        self.assertEqual(self.store.list('demo'),[])

    def test_folder_only_and_no_launch_authorization(self):
        self.save(executable='')
        self.assertEqual(self.store.list('demo')[0]['executable'],'')
        self.assertEqual(self.bridge.tickets,{})
        with self.assertRaises(ValueError):self.bridge.dispatch('launch',{'path':'Test:\\Games\\default.xex'})

    def test_disconnected_and_unavailable_folder(self):
        self.bridge.target=None
        with self.assertRaises(ValueError):self.save()
        self.bridge.target='demo'
        def unavailable(*a,**kw):raise ValueError('Offline')
        self.bridge.adapter=unavailable
        with self.assertRaises(ValueError):self.save()
        self.assertEqual(self.store.list('demo'),[])
