import json
import tempfile
import threading
import unittest
from pathlib import Path

from safe_io import atomic_write_json, update_json_locked


class SafeIoTests(unittest.TestCase):
    def test_atomic_json_can_be_reloaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            atomic_write_json(path, {"value": 1})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"value": 1})

    def test_locked_updates_do_not_lose_concurrent_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tokens.json"
            barrier = threading.Barrier(20)

            def worker(index):
                barrier.wait()

                def update(data):
                    values = list((data or {}).get("values") or [])
                    values.append(index)
                    return {"values": values}

                update_json_locked(path, update, default={})

            threads = [threading.Thread(target=worker, args=(index,)) for index in range(20)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(sorted(payload["values"]), list(range(20)))


if __name__ == "__main__":
    unittest.main()
