"""A tiny SMTP server for tests (127.0.0.1 only): EHLO, STARTTLS, AUTH PLAIN/LOGIN, MAIL,
RCPT, DATA, NOOP, RSET, QUIT. Responses can be scripted to simulate refusals."""

import base64
import socket
import ssl
import threading
from dataclasses import dataclass, field
from email import message_from_bytes, policy


@dataclass
class Behaviour:
    starttls: bool = True
    auth: tuple[str, str] | None = None  # expected (user, password)
    rcpt_reply: str = "250 OK"  # e.g. "450 Mailbox busy" or "550 No such user"
    data_reply: str = "250 Queued"


@dataclass
class Received:
    sender: str
    recipients: list
    raw: bytes
    tls: bool
    user: str | None

    @property
    def message(self):
        return message_from_bytes(self.raw, policy=policy.default)


@dataclass
class FakeSmtp:
    context: ssl.SSLContext | None
    behaviour: Behaviour = field(default_factory=Behaviour)
    received: list = field(default_factory=list)
    sessions: int = 0

    def start(self):
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.stop = False
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()
        return self

    def close(self):
        self.stop = True
        self.thread.join(timeout=2)
        self.sock.close()

    def _serve(self):
        while not self.stop:
            try:
                conn, _ = self.sock.accept()
            except (TimeoutError, OSError):
                continue
            self.sessions += 1
            try:
                self._session(conn)
            except (OSError, ssl.SSLError):
                pass
            finally:
                conn.close()

    def _session(self, conn):
        b = self.behaviour
        tls, user = False, None
        stream = conn.makefile("rwb")

        def send(line):
            stream.write(line.encode() + b"\r\n")
            stream.flush()

        def read():
            return stream.readline().decode().rstrip("\r\n")

        send("220 fake.smtp.test ESMTP")
        sender, recipients = "", []
        while True:
            line = read()
            if not line:
                return
            verb = line.split(" ", 1)[0].upper()
            if verb in ("EHLO", "HELO"):
                lines = ["250-fake.smtp.test"]
                if b.starttls and not tls:
                    lines.append("250-STARTTLS")
                if b.auth and (tls or not b.starttls):
                    lines.append("250-AUTH PLAIN LOGIN")
                lines.append("250 8BITMIME")
                for item in lines:
                    send(item)
            elif verb == "STARTTLS" and b.starttls and not tls:
                send("220 Go ahead")
                conn = self.context.wrap_socket(conn, server_side=True)
                stream = conn.makefile("rwb")
                tls = True
            elif verb == "AUTH":
                parts = line.split()
                if parts[1].upper() == "PLAIN":
                    raw = parts[2] if len(parts) > 2 else None
                    if raw is None:
                        send("334 ")
                        raw = read()
                    _, u, p = base64.b64decode(raw).decode().split("\0")
                else:
                    send("334 VXNlcm5hbWU6")
                    u = base64.b64decode(read()).decode()
                    send("334 UGFzc3dvcmQ6")
                    p = base64.b64decode(read()).decode()
                if b.auth and (u, p) == b.auth:
                    user = u
                    send("235 Authenticated")
                else:
                    send("535 5.7.8 Authentication credentials invalid")
            elif verb == "MAIL":
                sender, recipients = line.split(":", 1)[1].strip(" <>").split(">")[0], []
                send("250 OK")
            elif verb == "RCPT":
                code = b.rcpt_reply
                if code.startswith("2"):
                    recipients.append(line.split(":", 1)[1].strip(" <>"))
                send(code)
            elif verb == "DATA":
                send("354 End data with <CR><LF>.<CR><LF>")
                chunks = []
                while True:
                    data = stream.readline()
                    if data in (b".\r\n", b""):
                        break
                    chunks.append(data[1:] if data.startswith(b"..") else data)
                if b.data_reply.startswith("2"):
                    self.received.append(Received(sender, recipients, b"".join(chunks), tls, user))
                send(b.data_reply)
            elif verb == "NOOP":
                send("250 OK")
            elif verb == "RSET":
                send("250 OK")
            elif verb == "QUIT":
                send("221 Bye")
                return
            else:
                send("502 Command not implemented")
