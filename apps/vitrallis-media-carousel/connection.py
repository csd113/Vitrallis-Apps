"""Small, local-only QR codes. Access credentials are deliberately separate."""
import ipaddress
from urllib.parse import urlsplit


def qr_image(url):
    parts = urlsplit(url)
    try:
        address = ipaddress.ip_address(parts.hostname)
        valid = (parts.scheme == 'http' and address.is_private
                 and not address.is_loopback and not address.is_link_local
                 and not address.is_unspecified and not address.is_multicast
                 and not address.is_reserved
                 and not parts.username and parts.port and not parts.query
                 and not parts.fragment and parts.path in ('', '/'))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        return None
    import qrcode
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=3, border=4)
    code.add_data(url)
    code.make(fit=True)
    return code.make_image(fill_color='black', back_color='white').convert('RGB')
