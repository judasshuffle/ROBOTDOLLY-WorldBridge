import io
import struct
import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
from PIL import Image
from worldbridge import ktx
from worldbridge.recovery import Index, convert, sha
from worldbridge.reference import parse_location


class RecoveryTests(unittest.TestCase):
    def test_poc_all_pixels_repeatable(self):
        poc_dir = Path.home() / 'WorldBridge-KTX1-POC'
        if not (poc_dir / 'ktx1_decode.py').is_file():
            self.skipTest('External KTX1 POC fixtures unavailable')
        sys.path.insert(0, str(poc_dir))
        import ktx1_decode as poc
        for name, digest in poc.EXPECTED.items():
            raw = (poc.SOURCE/name).read_bytes()
            self.assertEqual(sha(raw), digest)
            pixels, details = ktx.decode(ktx.parse(raw), 'Normal' in name)
            reference, _ = poc.decode(poc.parse(raw), 'Normal' in name)
            np.testing.assert_array_equal(pixels, np.asarray(reference))
            encoded = ktx.png_bytes(pixels, 'Base' in name)
            np.testing.assert_array_equal(np.asarray(Image.open(io.BytesIO(encoded))), pixels)
            self.assertEqual(encoded, ktx.png_bytes(pixels, 'Base' in name))

    def test_reject_malformed(self):
        for raw in (b'', b'garbage', ktx.MAGIC+bytes(100)):
            with self.assertRaises(ValueError):
                ktx.parse(raw)

    def test_bc3_against_pillow(self):
        root=Path.home() / 'WorldBridge-Asset-Rescue-Fixtures'
        source=next(root.rglob('tex-b8bdc7bbac9bd995ecb828e558a87fa3eedb899892ce4a72f85b095b0b895561.ktx'), None)
        if source is None:
            self.skipTest('External BC3 test fixture unavailable')
        info=ktx.parse(source.read_bytes())
        pixels,_=ktx.decode(info)
        expected=Image.frombytes('RGBA',(info['width'],info['height']),info['levels'][0],'bcn',(3,'DXT5'))
        np.testing.assert_array_equal(pixels,np.asarray(expected))
        self.assertGreater(int(pixels[:,:,3].max()),int(pixels[:,:,3].min()))

    def test_hash_not_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root/'misleading.ktx'
            image.write_bytes(b'\x89PNG\r\n\x1a\nnot-valid-pixels')
            digest = sha(image.read_bytes())
            image.rename(root/('tex-'+digest+'.ktx'))
            index = Index([root])
            self.assertEqual(index.match('tex-'+digest+'.ktx')[1], digest)
            self.assertEqual(index.match('misleading.ktx')[2], 'missing')
            self.assertEqual(index.match('tex-'+'0'*64+'.ktx')[2], 'missing')

    def test_camera_coordinates(self):
        position, q = parse_location('hifi://offline/1,2,3/0,0,0,1')
        self.assertEqual(position, (1,-3,2))
        self.assertEqual(q, (1,0,0,0))
        for value in ('https://host/1,2,3/0,0,0,1', 'hifi://host/1,2,3/0,0,0,0', 'hifi://host/nan,2,3/0,0,0,1'):
            with self.assertRaises(ValueError):
                parse_location(value)


if __name__ == '__main__':
    unittest.main()
