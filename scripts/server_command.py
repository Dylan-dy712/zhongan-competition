"""Run an explicit maintenance command over verified SSH; never log credentials."""
import argparse
import sys

import paramiko


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', required=True)
    parser.add_argument('--key', required=True)
    parser.add_argument('--command', required=True)
    args = parser.parse_args()
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(args.host, username='ubuntu', key_filename=args.key,
                   timeout=15, allow_agent=False, look_for_keys=False)
    try:
        _, out, err = client.exec_command(args.command, timeout=600)
        # Drain both streams concurrently to avoid blocking on a full stderr pipe.
        import threading
        def drain(stream, target):
            for line in iter(stream.readline, ''):
                target.write(line)
                target.flush()
        threads = [threading.Thread(target=drain, args=(out, sys.stdout)),
                   threading.Thread(target=drain, args=(err, sys.stderr))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        raise SystemExit(out.channel.recv_exit_status())
    finally:
        client.close()


if __name__ == '__main__':
    main()
