"""Generate the intentional share link and high contrast QR assets, without account passwords."""
import argparse
import json
from pathlib import Path

import paramiko
import qrcode
import qrcode.image.svg
import requests
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', required=True)
    parser.add_argument('--key', required=True)
    args = parser.parse_args()
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(args.host, username='ubuntu', key_filename=args.key, timeout=15, allow_agent=False, look_for_keys=False)
    try:
        with client.open_sftp() as sftp:
            with sftp.open('/home/ubuntu/.config/zhongan/judge-demo.env') as handle:
                config = handle.read().decode().strip()
        prefix = 'ZHONGAN_JUDGE_ENTRY_KEY='
        if not config.startswith(prefix) or '\n' in config or len(config[len(prefix):]) != 43:
            raise RuntimeError('Invalid server-local invitation configuration')
        invitation = config[len(prefix):]
    finally:
        client.close()
    base = 'http://' + args.host
    session = requests.Session()
    session.trust_env = False
    health = session.get(base + '/judge/health', timeout=15)
    health.raise_for_status()
    assert health.json() == {'status':'ok', 'capacity':50}
    entry = session.get(base + '/judge/', timeout=15)
    entry.raise_for_status()
    assert 'entry.js' in entry.text and 'frame-ancestors' in entry.headers.get('Content-Security-Policy','')
    url = base + '/judge/#' + invitation
    output = ROOT / 'output_dir/judge-demo'
    output.mkdir(parents=True,exist_ok=True)
    (output/'体验链接.txt').write_text(url + '\n',encoding='utf-8')
    (output/'entry-link.json').write_text(json.dumps({'url':url},ensure_ascii=False),encoding='utf-8')
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_Q, box_size=20, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    qr_image = qr.make_image(fill_color='black', back_color='white').convert('RGB')
    qr_image.save(output/'评委体验二维码.png',dpi=(300,300))
    qr.make_image(image_factory=qrcode.image.svg.SvgPathImage).save(output/'评委体验二维码.svg')
    poster = Image.new('RGB',(1800,2300),'#f4faf7')
    draw = ImageDraw.Draw(poster)
    font_path = 'C:/Windows/Fonts/msyh.ttc'
    def text(y,value,size,color='#173f32'):
        font=ImageFont.truetype(font_path,size)
        box=draw.textbbox((0,0),value,font=font)
        draw.text(((1800-(box[2]-box[0]))/2,y),value,font=font,fill=color)
    draw.rounded_rectangle((90,90,1710,2200),radius=60,fill='white')
    text(190,'众安 · 暖愈智护',60,'#008b67')
    text(320,'评委专属体验',104)
    text(490,'扫一扫，即可进入',54,'#5f7e6b')
    poster.paste(qr_image,((1800-qr_image.width)//2,640))
    lower=640+qr_image.height
    text(lower+80,'无需注册 · 自动登录 · 独立账号',45,'#008b67')
    text(lower+185,'聊天与上传资料相互隔离',42,'#5f7e6b')
    text(lower+280,'同一浏览器再次扫码，继续原来的体验',35,'#738779')
    text(2110,'请使用虚构资料体验',32,'#738779')
    poster.save(output/'评委体验扫码海报.png',dpi=(300,300))
    print(json.dumps({'public_health':'ok','capacity':50,'qr_size':qr_image.size,'output':str(output)},ensure_ascii=False))


if __name__ == '__main__':
    main()
