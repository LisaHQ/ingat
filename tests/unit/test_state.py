import os
import stat
import tempfile
import unittest

from ingat.model.errors import CannotRun, Refused
from ingat.model.records import new_doc
from ingat.store import fs, state
from ingat.store.state import Layout


class LayoutTest(unittest.TestCase):
    def test_paths_follow_the_documented_layout(self) -> None:
        lay = Layout("/r/", "/b")
        i = "/r/instances/site"
        expected = [
            (lay.host_json, "/r/host.json"),
            (lay.host_lock, "/r/host.lock"),
            (lay.plans_dir, "/r/plans"),
            (lay.plan("f" * 64), "/r/plans/" + "f" * 64 + ".json"),
            (lay.cache_git("0123abcd"), "/r/cache/git/0123abcd.git"),
            (lay.cache_src("c" * 40), "/r/cache/src/" + "c" * 40),
            (lay.fixtures_dir, "/r/cache/fixtures"),
            (lay.keys_dir("deploy"), "/r/keys/deploy"),
            (lay.inbox, "/r/inbox"),
            (lay.runs_dir, "/r/host/runs"),
            (lay.ledger("ab12", "site-4"), "/r/host/images/ab12/site-4.json"),
            (lay.allocations_dir, "/r/host/allocations"),
            (lay.attention_json, "/r/host/attention.json"),
            (lay.certifications_dir, "/r/host/certifications"),
            (lay.inst("site"), i),
            (lay.inst_toml("site"), i + "/instance.toml"),
            (lay.record_json("site"), i + "/record.json"),
            (lay.lock("site"), i + "/lock"),
            (lay.secrets_dir("site"), i + "/secrets"),
            (lay.placeholder("site"), i + "/placeholder"),
            (lay.app_dir("site"), i + "/app"),
            (lay.candidates("site", "c" * 40, {"app": "img:1"}), i + "/candidates/" + "c" * 40 + "-804863dec759.json"),
            (lay.candidates("site", "c" * 40, {"app": "img:2"}), i + "/candidates/" + "c" * 40 + "-601e559f7a55.json"),
            (lay.env_dir("site"), i + "/env"),
            (lay.deployments_dir("site"), i + "/deployments"),
            (lay.deployment_json("site", 7), i + "/deployments/7.json"),
            (lay.deployment_snapshot("site", 7), i + "/deployments/7"),
            (lay.ops_dir("site"), i + "/ops"),
            (lay.op_dir("site", 12, "deploy"), i + "/ops/12-deploy"),
            (lay.catalog_dir("site"), i + "/catalog"),
            (lay.catalog("site", "B1"), i + "/catalog/B1.json"),
            (lay.verifications_dir("site", "B1"), i + "/verifications/B1"),
            (lay.reports_dir("site"), i + "/reports"),
            (lay.data_gen("site", "files", "g1"), "/r/data/site/files/g1"),
            (lay.data_gen("site", "files", "t9"), "/r/data/site/files/t9"),
            (lay.bundle_dir("site", "B1"), "/b/site/B1"),
            (lay.incoming_dir("site", "B1"), "/b/site/.incoming-B1"),
        ]
        for got, want in expected:
            self.assertEqual(got, want)

    def test_a_component_that_could_leave_its_directory_is_refused(self) -> None:
        lay = Layout("/r", "/b")
        for call in (
            lambda: lay.inst(".."),
            lambda: lay.plan("../x"),
            lambda: lay.record_json("a/b"),
            lambda: lay.catalog("site", "../x"),
            lambda: lay.bundle_dir("site", ".."),
            lambda: lay.op_dir("site", 1, "x/y"),
            lambda: lay.data_gen("site", "", "g1"),
        ):
            with self.assertRaises(Refused) as cm:
                call()
            self.assertEqual(cm.exception.code, "unsafe-path")


class StateTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.lay = Layout(os.path.join(tmp.name, "root"), os.path.join(tmp.name, "backups"))

    def record(self, name: str, **fields: object) -> None:
        state.write_doc_once(self.lay.record_json(name), new_doc("instance", name=name, **fields))

    def test_documents_round_trip_and_keep_unknown_fields(self) -> None:
        path = self.lay.record_json("site")
        self.record("site", next_seq=1, later_field={"x": [1]})
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        doc = state.read_doc(path, "instance")
        state.replace_doc(path, {**doc, "next_seq": 2})
        again = state.read_doc(path, "instance")
        self.assertEqual((again["next_seq"], again["later_field"]), (2, {"x": [1]}))
        with self.assertRaises(FileExistsError):
            self.record("site")

    def test_read_doc_refuses_another_kind_and_a_newer_schema(self) -> None:
        path = self.lay.host_json
        state.write_doc_once(path, {"state_schema": 2, "kind": "host"})
        with self.assertRaises(CannotRun) as cm:
            state.read_doc(path, "host")
        self.assertEqual(cm.exception.code, "newer-state")
        with self.assertRaises(Refused):
            state.read_doc(path, "instance")

    def test_list_instances_names_only_initialized_ones(self) -> None:
        self.assertEqual(state.list_instances(self.lay), [])
        self.record("web")
        self.record("lite-test")
        fs.mkdirs(self.lay.inst("half"))
        self.assertEqual(state.list_instances(self.lay), ["lite-test", "web"])

    def test_open_ops_and_next_seq(self) -> None:
        self.record("site", next_seq=3)
        self.assertEqual((state.open_ops(self.lay, "site"), state.next_seq(self.lay, "site")), ([], 3))
        fs.write_once(os.path.join(self.lay.op_dir("site", 1, "prepare"), "result.json"), b"{}")
        for seq, kind in ((2, "deploy"), (10, "backup")):
            fs.mkdirs(self.lay.op_dir("site", seq, kind))
        for other in ("notes", "03-old", "x-1"):
            fs.mkdirs(os.path.join(self.lay.ops_dir("site"), other))
        self.assertEqual(state.open_ops(self.lay, "site"), [(2, "deploy"), (10, "backup")])
        self.assertEqual(state.next_seq(self.lay, "site"), 11)
        path = self.lay.record_json("site")
        state.replace_doc(path, {**state.read_doc(path, "instance"), "next_seq": 20})
        self.assertEqual(state.next_seq(self.lay, "site"), 20)


if __name__ == "__main__":
    unittest.main()
