"""NapCat / OneBot v11 forward-WebSocket adapter for the Asuna runtime host.

Inbound events go to the host, outbound text comes only from the host outbox,
and every send is settled by the platform's real response (or `unknown`).
"""
__version__ = "0.5.2"
