import json
import tempfile
import unittest
from html.parser import HTMLParser
from urllib.parse import urljoin
from pathlib import Path
from scripts.build_proposal_preview import build_preview
from scripts.deploy_remote import validated_build


class MobileBuildTests(unittest.TestCase):
    def test_real_source_build_is_complete_private_file_free_and_immutable(self):
        source = Path(__file__).resolve().parents[1]/'output_dir/product-design'
        revision = 'a'*40
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'dist'
            result = build_preview(source, output, revision, '/.mobile-demo-releases/'+revision+'/')
            paths = validated_build(output, revision, mobile=True)
            self.assertEqual(len(paths), result['file_count']+1)
            self.assertTrue((output/'assets/onboard-document.webp').is_file())
            html = (output/'index.html').read_text(encoding='utf-8')
            self.assertIn('location.hash="/home"', html)
            class References(HTMLParser):
                def __init__(self):
                    super().__init__(); self.base = None; self.resources = []
                def handle_starttag(self, tag, attrs):
                    attrs = dict(attrs)
                    if tag=='base': self.base = attrs.get('href')
                    if tag=='script' and 'src' in attrs: self.resources.append(attrs['src'])
                    if tag=='link' and 'href' in attrs: self.resources.append(attrs['href'])
            parsed = References(); parsed.feed(html)
            self.assertIsNone(parsed.base)
            page = 'http://example.test/mobile-demo/'
            self.assertEqual(urljoin(parsed.base or page, '#/records'), page+'#/records')
            self.assertTrue(parsed.resources)
            for resource in parsed.resources:
                self.assertTrue(resource.startswith('/.mobile-demo-releases/'+revision+'/'))
                self.assertTrue((output/resource.split('/')[-1].split('?')[0]).is_file())
            self.assertIn('/.mobile-demo-releases/'+revision+'/assets/',
                          (output/'care-home.js').read_text(encoding='utf-8'))
            self.assertNotIn('README.md', {p.name for p in paths})
            self.assertFalse(any(p.suffix not in {'.html','.css','.js','.webp','.json',''} for p in paths))
            with self.assertRaises(FileExistsError):
                build_preview(source, output, revision)
            with self.assertRaises(SystemExit):
                validated_build(output, 'b'*40, mobile=True)
            (output/'encounter-data.js').write_text('tampered')
            with self.assertRaises(SystemExit):
                validated_build(output, revision, mobile=True)

    def test_unreferenced_files_are_not_published_and_missing_assets_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'source'
            source.mkdir()
            (source/'home-proposal.html').write_text('<head></head><script src="app.js?v=1"></script>')
            (source/'app.js').write_text('const image="assets/sample.webp";')
            (source/'patient.pdf').write_bytes(b'private synthetic placeholder')
            (source/'assets').mkdir()
            output = Path(directory)/'dist'
            with self.assertRaises(ValueError):
                build_preview(source, output, 'a'*40)
            self.assertFalse(output.exists())
            (source/'assets/sample.webp').write_bytes(b'synthetic image placeholder')
            build_preview(source, output, 'a'*40, '/.mobile-demo-releases/'+'a'*40+'/')
            self.assertFalse((output/'patient.pdf').exists())
            (output/'unexpected.txt').write_text('unexpected')
            with self.assertRaises(SystemExit):
                validated_build(output, 'a'*40, mobile=True)

    def test_revision_base_and_manifest_cannot_be_silently_changed(self):
        source = Path(__file__).resolve().parents[1]/'output_dir/product-design'
        with tempfile.TemporaryDirectory() as directory:
            for revision, base in [('main','/mobile-demo/'),('a'*40,'/../secrets/'),('a'*40,'https://example.com/')]:
                with self.subTest(revision=revision,base=base), self.assertRaises(ValueError):
                    build_preview(source, Path(directory)/'invalid', revision, base)
            output = Path(directory)/'dist'
            build_preview(source, output, 'a'*40)
            with self.assertRaises(SystemExit):
                validated_build(output, 'a'*40, mobile=True)
            self.assertTrue(json.loads((output/'manifest.json').read_text()))
