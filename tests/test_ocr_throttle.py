import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from services.api.app.ocr_throttle import ocr_request_slot


class OcrThrottleTests(unittest.TestCase):
    def test_in_flight_calls_are_serialized_and_spacing_applies_after_failure(self):
        started = threading.Event()
        times = {}
        def first():
            try:
                with ocr_request_slot(interval=.03):
                    started.set()
                    time.sleep(.03)
                    times['finished'] = time.monotonic()
                    raise RuntimeError('synthetic timeout')
            except RuntimeError:
                pass
        def second():
            started.wait(2)
            with ocr_request_slot(interval=.03):
                times['second'] = time.monotonic()
        threads = [threading.Thread(target=first), threading.Thread(target=second)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(3)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertGreaterEqual(times['second']-times['finished'], .025)

    @unittest.skipUnless(os.name == 'posix', 'Cross-process file locks are used by Linux deployment')
    def test_independent_api_and_worker_processes_share_the_interval(self):
        script = '''import json,sys,time
from services.api.app.ocr_throttle import ocr_request_slot
with ocr_request_slot(sys.argv[1], interval=.05):
    start=time.time()
    time.sleep(.03)
    end=time.time()
print(json.dumps([start,end]))
'''
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/'synthetic-ocr.lock')
            processes = [subprocess.Popen([sys.executable, '-c', script, path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
            times = []
            for process in processes:
                out, err = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, err)
                times.append(json.loads(out))
            times.sort()
            self.assertGreaterEqual(times[1][0]-times[0][1], .04)
            self.assertEqual(Path(path).stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
