from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import signal

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from player import EXTENSIONS, Player, Track, metadata, next_index, scan
from storage import Paths, read_state, write_state


class LibraryTests(unittest.TestCase):
    def test_empty_missing_supported_recursive_order_and_links(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve()
            self.assertEqual(scan(root)[0],[])
            self.assertEqual(scan(root/'missing')[0],[])
            (root/'Album').mkdir()
            for extension in EXTENSIONS:(root/'Album'/('Track'+extension.upper())).write_bytes(b'bad')
            (root/'Ignore.txt').write_text('ignored')
            (root/'loop').symlink_to(root,target_is_directory=True)
            tracks,warning=scan(root)
            self.assertEqual(len(tracks),len(EXTENSIONS))
            self.assertEqual(tracks,sorted(tracks,key=lambda p:(str(p.relative_to(root)).casefold(),str(p))))
            self.assertEqual(warning,'')

    def test_cancel_and_entry_limit(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            for i in range(10):(root/f'{i}.mp3').write_bytes(b'')
            self.assertEqual(scan(root,lambda:True)[0],[])
            with patch('player.MAX_TRACKS',3):
                tracks,warning=scan(root)
            self.assertEqual(len(tracks),3)
            self.assertIn('limit',warning)

    def test_corrupt_media_and_missing_tools_fall_back(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'Title.mp3';path.write_bytes(b'corrupt')
            item=metadata(path)
            self.assertEqual(item.title,'Title')
            self.assertTrue(item.error)
            with patch('player.shutil.which',return_value=None):item=metadata(path)
            self.assertEqual(item.artist,'Unknown artist')
            self.assertTrue(item.error)

    def test_metadata_normalization_and_duration(self):
        with patch('player.shutil.which',return_value='/ffprobe'),patch('player.bounded_command',return_value=b'{"format":{"duration":"42.5","tags":{"TITLE":"A\\nB","ARTIST":"Artist","ALBUM":"Album"}}}'):
            track=metadata(Path('/music/track.flac'))
        self.assertEqual((track.title,track.artist,track.album,track.duration),('AB','Artist','Album',42.5))

    def test_modes_and_end_of_library(self):
        self.assertIsNone(next_index(0,0))
        self.assertIsNone(next_index(1,2))
        self.assertEqual(next_index(1,2,repeat='all'),0)
        self.assertEqual(next_index(1,2,repeat='one'),1)
        self.assertEqual(next_index(1,2,shuffle=True),0)


class FakeProcess:
    def __init__(self):self.signals=[];self.returncode=None;self.waits=0
    def poll(self):return self.returncode
    def send_signal(self,s):self.signals.append(s)
    def terminate(self):self.returncode=0
    def kill(self):self.returncode=-9
    def wait(self,timeout=None):self.waits+=1;return self.returncode


class PlaybackTests(unittest.TestCase):
    def setUp(self):
        self.now=[10.0];self.spawned=[];self.arguments=[]
        def spawn(args,**kwargs):
            self.arguments.append(args);process=FakeProcess();self.spawned.append(process);return process
        self.player=Player(lambda:self.now[0],spawn)
        self.track=Track(Path('/a b.mp3'),'Title',duration=60)
        self.tool=patch('player.shutil.which',return_value='/ffplay');self.tool.start();self.addCleanup(self.tool.stop)
        self.addCleanup(self.player.stop)

    def test_pause_resume_seek_volume_and_owned_cleanup(self):
        self.assertTrue(self.player.play(self.track))
        self.now[0]+=5
        self.assertEqual(self.player.position(),5)
        self.player.pause();self.now[0]+=10
        self.assertEqual(self.player.position(),5)
        self.assertIn(signal.SIGSTOP,self.spawned[0].signals)
        self.player.pause();self.now[0]+=2
        self.assertEqual(self.player.position(),7)
        self.player.seek(20)
        self.assertEqual(self.spawned[0].waits,1)
        self.player.set_volume(150)
        self.assertEqual(self.player.volume,100)
        self.assertIn('/a b.mp3',self.arguments[-1])
        self.player.stop();self.assertIsNone(self.player.process)
        self.assertTrue(all(p.waits==1 for p in self.spawned))

    def test_paused_stop_resumes_before_termination(self):
        self.player.play(self.track);self.player.pause();p=self.player.process
        self.player.stop();self.assertIn(signal.SIGCONT,p.signals)

    def test_failed_decode_does_not_auto_advance(self):
        self.player.play(self.track);self.player.process.returncode=1
        self.assertFalse(self.player.finished());self.assertTrue(self.player.error)

    def test_missing_backend_and_bad_track(self):
        with patch('player.shutil.which',return_value=None):self.assertFalse(self.player.play(self.track))
        self.assertFalse(self.player.play(Track(Path('/bad.mp3'),'bad',error='corrupt')))

    def test_preferences_survive_package_replacement(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve();paths=Paths('io.vitrallis.music',{'HOME':str(root)})
            write_state(paths.state/'settings.json',{'volume':45,'repeat':'all'})
            self.assertEqual(read_state(paths.state/'settings.json')['volume'],45)
            self.assertFalse(paths.documents.exists())
            self.assertNotIn('apps',paths.state.parts)


class DecoderTests(unittest.TestCase):
    def test_real_formats_decode_to_null_without_audio_device(self):
        import shutil,subprocess
        ffmpeg=shutil.which('ffmpeg')
        if not ffmpeg:self.skipTest('System FFmpeg unavailable')
        with tempfile.TemporaryDirectory() as t:
            for extension in ('.mp3','.flac','.ogg','.wav'):
                path=Path(t)/('Sample'+extension)
                subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','anullsrc=r=22050:cl=mono','-t','0.25',str(path)],check=True,timeout=10)
                track=metadata(path)
                self.assertFalse(track.error)
                self.assertGreater(track.duration,0)
                subprocess.run([ffmpeg,'-v','error','-i',str(path),'-f','null','-'],check=True,timeout=10,stdout=subprocess.DEVNULL)

    def test_probe_close_prevents_new_children(self):
        from player import Probe
        probe=Probe();probe.close()
        with self.assertRaises(ValueError):probe([sys.executable,'-c','print(1)'])


@unittest.skipUnless(sys.platform=='linux','Linux parent-death signal integration')
class ParentDeathTests(unittest.TestCase):
    def test_abrupt_parent_death_closes_exec_decoder(self):
        import os,subprocess,time
        helper=Path(__file__).resolve().parents[1]/'owned_child.py'
        with tempfile.TemporaryDirectory() as t:
            ready=Path(t)/'ready'
            target=f'import pathlib,time;pathlib.Path({str(ready)!r}).write_text("ready");time.sleep(60)'
            parent_code=f'import os,subprocess,sys,time;p=subprocess.Popen([sys.executable,"-I","-B",{str(helper)!r},str(os.getpid()),sys.executable,"-c",{target!r}],stdout=subprocess.DEVNULL);print(p.pid,flush=True);time.sleep(60)'
            parent=subprocess.Popen([sys.executable,'-I','-c',parent_code],stdout=subprocess.PIPE,text=True)
            child=int(parent.stdout.readline())
            try:
                end=time.monotonic()+3
                while not ready.exists() and time.monotonic()<end:time.sleep(.01)
                self.assertTrue(ready.exists())
                parent.kill();parent.wait(timeout=2)
                end=time.monotonic()+3
                while time.monotonic()<end:
                    try:state=Path(f'/proc/{child}/stat').read_text().split(') ',1)[1].split()[0]
                    except FileNotFoundError:break
                    if state=='Z':break
                    time.sleep(.01)
                else:self.fail('Decoder remained live after its parent died')
            finally:
                if parent.poll() is None:parent.kill();parent.wait(timeout=2)
                parent.stdout.close()
                try:os.kill(child,signal.SIGKILL)
                except ProcessLookupError:pass


class ArtworkTests(unittest.TestCase):
    def test_embedded_art_is_scaled_before_retention(self):
        import shutil,subprocess,io
        from PIL import Image
        ffmpeg=shutil.which('ffmpeg')
        if not ffmpeg:self.skipTest('FFmpeg unavailable')
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);art=root/'cover.png';Image.new('RGB',(600,400),'blue').save(art)
            track=root/'Artwork.mp3'
            subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','anullsrc=r=22050:cl=mono','-i',str(art),
                            '-map','0:a','-map','1:v','-c:v','png','-disposition:v','attached_pic','-t','0.25',str(track)],check=True,timeout=10)
            item=metadata(track)
            self.assertFalse(item.error);self.assertTrue(item.art)
            image=Image.open(io.BytesIO(item.art));self.assertLessEqual(max(image.size),112)


@unittest.skipUnless(sys.platform=='linux','Linux SDL dummy audio backend')
class DummyAudioTests(unittest.TestCase):
    def test_real_decoder_pause_seek_volume_and_reaping_without_speakers(self):
        import os,shutil,time,wave
        if not shutil.which('ffplay'):self.skipTest('System FFplay unavailable')
        with tempfile.TemporaryDirectory() as t,patch.dict(os.environ,{'SDL_AUDIODRIVER':'dummy'}):
            path=Path(t)/'silence.wav'
            with wave.open(str(path),'wb') as f:
                f.setnchannels(1);f.setsampwidth(2);f.setframerate(11025);f.writeframes(bytes(11025*2*4))
            player=Player()
            try:
                self.assertTrue(player.play(Track(path,'Silence',duration=4)))
                time.sleep(.25);self.assertIsNone(player.process.poll())
                player.pause();position=player.position();time.sleep(.05);self.assertEqual(player.position(),position)
                player.seek(1);self.assertTrue(player.paused)
                player.pause();player.set_volume(30)
                process=player.process;player.stop();self.assertIsNotNone(process.poll());self.assertIsNone(player.process)
            finally:player.stop()


class ProtocolTests(unittest.TestCase):
    def test_media_cannot_enable_network_protocols(self):
        import socket,shutil
        if not shutil.which('ffprobe'):self.skipTest('FFprobe unavailable')
        with tempfile.TemporaryDirectory() as t,socket.socket() as listener:
            listener.bind(('127.0.0.1',0));listener.listen();listener.settimeout(.1)
            path=Path(t)/'misleading.mp3'
            path.write_text('#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\nhttp://127.0.0.1:'+str(listener.getsockname()[1])+'/segment.ts\n#EXT-X-ENDLIST\n')
            item=metadata(path)
            self.assertTrue(item.error)
            with self.assertRaises(TimeoutError):listener.accept()
