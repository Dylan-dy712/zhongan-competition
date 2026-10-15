# 医疗服务卡片插画

2026-10-16，使用内置 imagegen 生图模型生成三张新插画，非CLI/API脚本。仅作场景装饰，不代表真实机构照片或医生身份。权益、医院名称、使用条件和按钮仍由网页实时渲染。

## 素材与大小

最终资源在 `apps/web/src/assets/medical-services/`。每类提供384×192及768×384的WebP，按浏览器显示宽度和像素密度自动选择，使用懒加载、异步解码和固定比例预留空间。

- 权益：`benefit-v1-384.webp` 5,482字节；`benefit-v1-768.webp` 15,090字节。
- 医院：`hospital-v1-384.webp` 10,258字节；`hospital-v1-768.webp` 32,170字节。
- 在线：`online-v1-384.webp` 6,268字节；`online-v1-768.webp` 16,362字节。
- 三张小图合计22,008字节，三张大图合计63,622字节。相同医院插画跨卡片复用同一URL，可被浏览器缓存。
- 原始1774×887的PNG保存在 `output_dir/medical-service-card-art-20261016/originals/`，不导入网页、不纳入发布素材。尺寸缩放和WebP压缩由 `scripts/optimize_medical_service_art.py` 完成，没有改变图像内容。
- 卡片插画显示高度桌面不超过166px、手机不超过152px，保留正文和操作空间；医院插画旁显示“就医场景示意”。

## 完整生成提示词

三次独立生成，每次将以下通用前缀与对应主题拼接，`transparent_background=false`，没有引用图或编辑目标。

### 通用前缀

Use case: stylized-concept. Asset type: production illustration for an existing Chinese medical-care recommendation card, not a screenshot or a finished UI card. Style: sophisticated friendly 3D clay editorial illustration, softly rounded shapes, matte porcelain and frosted glass, delicate shadows, very clean premium health app aesthetic. Palette coordinated with a mint-green medical app: pale ivory, celadon, mint, emerald accents, tiny warm cream highlights. Wide horizontal 2:1 composition. Main objects compact and fully visible in the central horizontal band, generous uncluttered pale mint background, suitable for a small 400px-wide card banner. Consistent eye-level three-quarter camera, soft daylight. No typography, letters, numbers, logos, labels, watermark, buttons, border, or UI. No Red Cross emblem. Decorative artwork only, should not imply any particular real hospital, clinician, insurance coverage or confirmed booking.

### 权益主题

Subject: a beautifully arranged medical benefits still-life: a soft mint protective shield with a small embossed heart, a cream blank health-check booklet, a stethoscope, one tiny sprout. Balanced compact sculptural composition, warm caring mood. Do not add people, pills or large floating icons.

### 医院主题

Subject: a welcoming generic modern low-rise hospital building in matte white and celadon glass, one gently curving path, small sculptural trees and a single mint location pin. No hospital name, no emergency vehicles, no medical cross signs, no text. A calm miniature architectural scene, not a real institution's photograph.

### 在线主题

Subject: a friendly Chinese woman clinician in a white coat with a mint collar, bust portrait shown inside a rounded tablet screen, simple mint chat bubble beside it, softly rounded small desk base. Calm professional expression and natural proportions, compact minimal 3D clay illustration. No real person's likeness, no headset, no text, no duplicate faces or extra hands.
