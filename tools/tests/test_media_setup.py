import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import install_carousel_media_support as setup


class MediaSetupTests(unittest.TestCase):
    def test_policy_grants_only_fixed_argument_free_command(self):
        policy = setup.policy('chip').decode()
        self.assertIn('NOPASSWD: /usr/local/libexec/vitrallis-carousel-install-media ""', policy)
        for username in ('root ALL=', 'chip\nroot', '../chip', '-chip', '', 'chip;id'):
            with self.subTest(username=username), self.assertRaises(ValueError):
                setup.policy(username)

    def test_helper_has_no_caller_package_or_command_arguments(self):
        helper = setup.HELPER.decode()
        self.assertIn('[ "$#" -eq 0 ] || exit 64', helper)
        self.assertIn('--no-install-recommends --no-remove -y install ffmpeg', helper)
        self.assertNotIn('$@', helper)
        self.assertNotIn(' upgrade', helper)

    def test_unmanaged_file_is_preserved_before_temporary_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'policy'
            path.write_bytes(b'An administrator owns this file.\n')
            with patch.object(setup, 'secure'), patch.object(setup.tempfile, 'mkstemp') as create:
                with self.assertRaisesRegex(ValueError, 'unmanaged'):
                    setup.replace(path, b'replacement', 0o440)
                create.assert_not_called()
            self.assertEqual(path.read_bytes(), b'An administrator owns this file.\n')
