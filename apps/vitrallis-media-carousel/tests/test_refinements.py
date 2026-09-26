import io
import json
import subprocess
import zipfile
from unittest.mock import Mock, patch

from support import StorageCase, png_bytes
from support import WebCase
from multimedia import capabilities, decode_check
from previews import thumbnail


class DownloadTests(WebCase):
    def test_folder_archive_filenames_duplicates_and_cleanup(self):
        self.upload('one.png')
        self.upload('one.png')
        before = set(self.paths.data.iterdir())
        status, raw, headers = self.request('GET', f'/api/collections/{self.cid}/download')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'application/zip')
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertEqual(len(archive.namelist()), 2)
            self.assertIn('one.png', archive.namelist())
            for name in archive.namelist():
                self.assertEqual(archive.read(name), png_bytes())
        self.assertEqual(set(self.paths.data.iterdir()), before)

    def test_download_and_preview_auth_paths_and_symlinks(self):
        item = self.upload()[1]
        path = f'/api/collections/{self.cid}/media/{item["id"]}/thumbnail'
        self.assertEqual(self.request('GET', path, authorized=False)[0], 401)
        self.assertEqual(self.request('GET', f'/api/collections/{self.cid}/download', authorized=False)[0], 401)
        original = self.paths.media / item['id']
        original.unlink()
        original.symlink_to('/etc/passwd')
        self.assertIn(self.request('GET', path)[0], (400, 507))
        self.assertIn(self.request('GET', f'/api/collections/{self.cid}/download')[0], (400, 507))

    def test_thumbnail_decoded_once_and_bounded(self):
        item = self.upload()[1]
        path = f'/api/collections/{self.cid}/media/{item["id"]}/thumbnail'
        with patch.object(self.server.processes, 'start', wraps=self.server.processes.start) as start:
            first = self.request('GET', path)
            second = self.request('GET', path)
        self.assertEqual(first[0], 200)
        self.assertEqual(first[1], second[1])
        self.assertEqual(start.call_count, 1)
        self.assertLess(len(first[1]), 65536)


class CapabilityTests(StorageCase):
    def test_http_poll_keeps_last_result_during_background_recheck(self):
        import multimedia
        previous = capabilities()
        with multimedia._LOCK, patch('multimedia._detect') as detect:
            self.assertEqual(capabilities(blocking=False), previous)
            detect.assert_not_called()

    def test_presence_without_decode_is_not_ready(self):
        with patch('multimedia.executable_key', return_value=('/fake/ffmpeg', 1, 1)), patch('multimedia.decode_check', return_value=False):
            result = capabilities(refresh=True)
            self.assertFalse(result['ready'])
            self.assertIn('vp8', result['missing'])
        capabilities(refresh=True)

    def test_partial_capability_reports_the_missing_format(self):
        with patch('multimedia.executable_key', return_value=('/fake/ffmpeg', 1, 1)), patch('multimedia.decode_check', side_effect=[True, True, False]):
            result = capabilities(refresh=True)
            self.assertTrue(result['webm'])
            self.assertFalse(result['ready'])
            self.assertEqual(result['missing'], ['webp'])
        capabilities(refresh=True)

    def test_successful_exit_without_pixels_and_timeout_fail(self):
        info = Mock(returncode=0, stdout=b'16,16\n')
        with patch('multimedia.subprocess.run', side_effect=[info, Mock(returncode=0, stdout=b'')]):
            self.assertFalse(decode_check('ffmpeg', 'ffprobe', 'sample'))
        with patch('multimedia.subprocess.run', side_effect=subprocess.TimeoutExpired('ffmpeg', 5)):
            self.assertFalse(decode_check('ffmpeg', 'ffprobe', 'sample'))

    def test_preview_keeps_aspect_and_first_animation_frame(self):
        with io.BytesIO(png_bytes(size=(800,400))) as stream:
            result = thumbnail(stream, 'png')
            self.assertEqual(result.size, (128,64))

class ConnectionTests(StorageCase):
    def test_qr_uses_current_private_url_without_access_token(self):
        from connection import qr_image
        self.assertIsNone(qr_image('http://127.0.0.1:8765'))
        self.assertIsNone(qr_image('http://example.com:8765'))
        self.assertIsNone(qr_image('http://10.0.0.1:8765/?token=secret'))
        # Addresses that cannot be reached by another device must never be encoded.
        for unusable in ('http://169.254.10.4:8765', 'http://0.0.0.0:8765',
                         'http://255.255.255.255:8765', 'http://224.0.0.1:8765',
                         'https://10.0.0.1:8765', 'http://10.0.0.1'):
            self.assertIsNone(qr_image(unusable), unusable)
        first = qr_image('http://10.0.0.1:8765')
        second = qr_image('http://10.0.0.2:8765')
        self.assertLessEqual(first.width, 120)
        self.assertNotEqual(first.tobytes(), second.tobytes())

    def test_address_refresh_tracks_interface_change(self):
        from web_server import WebServer
        server = WebServer(self.library, self.settings)
        with patch('web_server.lan_addresses', return_value=['10.0.0.1']):
            server.refresh_addresses()
        self.assertEqual(server.urls, ['http://10.0.0.1:8765'])
        with patch('web_server.lan_addresses', return_value=['10.0.0.2']):
            server.refresh_addresses()
        self.assertEqual(server.urls, ['http://10.0.0.2:8765'])


class InstallationTests(StorageCase):
    def test_ready_system_does_not_run_installer(self):
        from dependencies import Installation
        with patch('dependencies.capabilities', return_value={'ready': True}), patch('dependencies.run_installer') as run:
            self.assertEqual(Installation().start()['status'], 'ready')
            run.assert_not_called()

    def test_success_requires_post_install_decode(self):
        from dependencies import Installation
        installation = Installation()
        with patch('dependencies.run_installer', return_value=(0, '')), patch('dependencies.capabilities', return_value={'ready': False,'webm_note':'Missing webp'}) as check:
            installation._run()
        self.assertEqual(installation.snapshot()['status'], 'failed')
        self.assertEqual(check.call_count, 2)
        check.assert_called_with(refresh=True)

    def test_installer_diagnostics_keep_only_bounded_tail(self):
        from dependencies import run_installer
        process = Mock()
        process.stderr = io.BytesIO(b'x' * 100000 + b' useful failure')
        process.wait.return_value = 42
        context = Mock()
        context.__enter__ = Mock(return_value=process)
        context.__exit__ = Mock(return_value=False)
        with patch('dependencies.subprocess.Popen', return_value=context):
            code, diagnostic = run_installer()
        self.assertEqual(code, 42)
        self.assertLessEqual(len(diagnostic), 2000)
        self.assertTrue(diagnostic.endswith('useful failure'))

    def test_cold_failed_check_is_retried_before_package_mutation(self):
        from dependencies import Installation
        installation = Installation()
        with patch('dependencies.capabilities', return_value={'ready': True}), patch('dependencies.run_installer') as run:
            installation._run()
            run.assert_not_called()
        self.assertEqual(installation.snapshot()['status'], 'ready')
