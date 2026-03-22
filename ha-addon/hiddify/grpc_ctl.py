#!/usr/bin/env python3
"""
Minimal gRPC control for hiddify-core v4.
Sends Core.Start / Core.Stop / Core.GetSystemInfo via raw HTTP/2.
Usage: grpc_ctl.py [start|stop|status] [--port 17078]
"""
import sys
import socket
import struct
import time

PORT = 17078


def h2_frame(type_, flags, stream_id, payload=b''):
    return struct.pack('>I', len(payload))[1:] + \
           bytes([type_, flags]) + \
           struct.pack('>I', stream_id) + payload


def hpack_str(s):
    b = s.encode() if isinstance(s, str) else s
    return bytes([len(b)]) + b


def grpc_call(method_path, body=b'', port=PORT, timeout=8):
    h2 = h2_frame
    hs = hpack_str
    authority = f'127.0.0.1:{port}'

    hpack = (
        bytes([0x83])
        + bytes([0x86])
        + bytes([0x44]) + hs(method_path)
        + bytes([0x41]) + hs(authority)
        + bytes([0x40]) + hs('content-type') + hs('application/grpc')
        + bytes([0x40]) + hs('te') + hs('trailers')
    )

    grpc_msg = b'\x00' + struct.pack('>I', len(body)) + body

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(('127.0.0.1', port))

        s.sendall(
            b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n'
            + h2(0x04, 0x00, 0)
            + h2(0x01, 0x04, 1, hpack)
            + h2(0x00, 0x01, 1, grpc_msg)
        )

        resp = b''
        while True:
            try:
                chunk = s.recv(4096)
                if not chunk:
                    break
                resp += chunk
                if len(resp) > 100:
                    break
            except socket.timeout:
                break
        s.close()
        return True, resp
    except Exception as e:
        return False, str(e).encode()


def wait_ready(port=PORT, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            s.connect(('127.0.0.1', port))
            s.close()
            return True
        except Exception:
            time.sleep(1)
    return False


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('action', choices=['start', 'stop', 'status', 'wait'])
    ap.add_argument('--port', type=int, default=PORT)
    ap.add_argument('--timeout', type=int, default=30)
    args = ap.parse_args()

    if args.action == 'wait':
        ok = wait_ready(args.port, args.timeout)
        if ok:
            print("gRPC ready")
            sys.exit(0)
        else:
            print("gRPC not ready (timeout)")
            sys.exit(1)

    if args.action == 'start':
        # Try with config_path in protobuf body (field 1, string)
        config_path = b'/data/hiddify/work/data/current-config.json'
        body = bytes([0x0a, len(config_path)]) + config_path
        ok, resp = grpc_call('/hiddify.v1.CoreService/Start', body=body, port=args.port)
        if not ok:
            # Fallback: empty body
            ok, resp = grpc_call('/hiddify.v1.CoreService/Start', body=b'', port=args.port)
    elif args.action == 'stop':
        ok, resp = grpc_call('/hiddify.v1.CoreService/Stop', port=args.port)
    elif args.action == 'status':
        ok, resp = grpc_call('/hiddify.v1.CoreService/GetSystemInfo', port=args.port)

    if ok:
        print(f"OK ({len(resp)} bytes)")
        sys.exit(0)
    else:
        print(f"FAIL: {resp.decode(errors='replace')}")
        sys.exit(1)


if __name__ == '__main__':
    main()
