import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import apps_added  # noqa: E402
import server  # noqa: E402
server.log.disabled = True

PROGRAMS = [("Stremio", r"C:\Users\x\AppData\Local\Programs\Stremio\stremio-shell-ng.exe"),
            ("Calculator", "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App")]


class MakeTile(unittest.TestCase):
    def test_store_app_opens_like_the_start_menu(self):
        t = apps_added.make_tile("program", "", "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App", PROGRAMS)
        self.assertEqual(t["name"], "Calculator")
        self.assertTrue(t["target"].lower().endswith("explorer.exe"))
        self.assertEqual(t["args"], ["shell:AppsFolder\\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"])

    def test_program_path_becomes_the_program_itself(self):
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d) / "tool.exe"
            exe.write_bytes(b"")
            self.assertEqual(apps_added.tile_for("Tool", str(exe)), {"name": "Tool", "kind": "exe", "target": str(exe)})

    def test_known_folder_ids_are_resolved(self):
        with mock.patch.dict(apps_added.KNOWN_FOLDERS, {"{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}": "C:\\PF86"}), \
                mock.patch.object(apps_added.Path, "is_file", return_value=True):
            t = apps_added.tile_for("Steam", "{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}\\Steam\\steam.exe")
        self.assertEqual(t["target"], "C:\\PF86\\Steam\\steam.exe")

    def test_only_start_menu_programs(self):
        with self.assertRaises(ValueError):
            apps_added.make_tile("program", "x", r"C:\Windows\System32\cmd.exe", PROGRAMS)

    def test_websites_must_be_https(self):
        t = apps_added.make_tile("web", "", "https://www.twitch.tv/", [])
        self.assertEqual((t["name"], t["kind"], t["target"]), ("twitch.tv", "web", "https://www.twitch.tv/"))
        for bad in ("http://example.com", "file:///C:/x", "javascript:alert(1)", "https://", "https://a b.com"):
            with self.assertRaises(ValueError, msg=bad):
                apps_added.make_tile("web", "x", bad, [])

    def test_names_lose_control_characters_and_stay_short(self):
        t = apps_added.make_tile("web", "Twi\x00tch\n" + "x" * 60, "https://twitch.tv", [])
        self.assertEqual(t["name"], "Twitch" + "x" * 34)

    def test_start_menu_filter(self):
        self.assertTrue(apps_added.keep("Steam", "{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}\\Steam\\steam.exe"))
        self.assertFalse(apps_added.keep("Uninstall SimHub", "x\\unins000.exe"))
        self.assertFalse(apps_added.keep("Discord", "https://www.geeks3d.com/discord/"))
        self.assertFalse(apps_added.keep("Readme", "C:\\x\\readme.txt"))

    def test_ids_never_clash(self):
        self.assertEqual(apps_added.new_id("Twitch TV", {"my-twitch-tv"}), "my-twitch-tv-1")
        self.assertEqual(apps_added.new_id("???", set()), "my-app")


class AddRemove(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.choices = Path(d.name) / "choices.json"
        p = mock.patch.object(server, "CHOICES_FILE", self.choices)
        p.start()
        self.addCleanup(p.stop)

    def test_added_site_is_a_tile_until_removed(self):
        app_id = server.add_app("web", "Twitch", "https://www.twitch.tv")
        apps, _ = server.load_apps()
        self.assertIn(app_id, [a["id"] for a in apps])
        self.assertEqual(json.loads(self.choices.read_text())["added"][0]["target"], "https://www.twitch.tv")
        server.remove_app(app_id)
        self.assertNotIn(app_id, [a["id"] for a in server.load_apps()[0]])

    def test_built_in_tiles_cant_be_removed(self):
        with self.assertRaises(ValueError):
            server.remove_app("youtube")


class Arrange(unittest.TestCase):
    APPS = [{"id": "steam"}, {"id": "epic"}, {"id": "ea"}, {"id": "youtube"}]

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        for p in (mock.patch.object(server, "CHOICES_FILE", Path(d.name) / "choices.json"),
                  mock.patch.object(server, "load_apps", return_value=(list(self.APPS), set()))):
            p.start()
            self.addCleanup(p.stop)

    def ids(self, apps):
        return [a["id"] for a in apps]

    def test_order_is_kept_and_new_apps_go_last(self):
        server.arrange_apps("order", ids=["youtube", "steam"])
        shown, _ = server.shown_apps()
        self.assertEqual(self.ids(shown), ["youtube", "steam", "epic", "ea"])

    def test_hide_and_unhide(self):
        server.arrange_apps("hide", "ea")
        shown, hidden = server.shown_apps()
        self.assertEqual((self.ids(shown), self.ids(hidden)), (["steam", "epic", "youtube"], ["ea"]))
        server.arrange_apps("unhide", "ea")
        self.assertEqual(server.shown_apps()[1], [])

    def test_unknown_apps_are_refused(self):
        for action, app_id, ids in (("order", "", ["steam", "evil"]), ("hide", "nope", ()), ("order", "", [])):
            with self.assertRaises(ValueError):
                server.arrange_apps(action, app_id, ids)


if __name__ == "__main__":
    unittest.main()
