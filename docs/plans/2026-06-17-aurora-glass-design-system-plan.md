# Aurora Glass Design System: 前端核心视觉与交互重构规范 v1.0

> 状态：核心基础与阅读/资料生成增强已落地（2026-06-09）。
> 已实现 `tokens.css` / `typography.css` 的 Aurora token 映射，接入 app chrome、历史侧栏、Chat 消息流与工具卡基础样式、在线考试暗场画布与题卡/手写板/导航 surface，并补充 token presence 与核心组件回归测试。资料详情页已接入 theatre reading/parallax surface，自学资料生成 SubAgent 研究区已接入 glass sidecar 与运行态边缘光。全站逐屏精修保留为后续视觉增强。

本规范作为前端重构的唯一真理来源 (Single Source of Truth)，采用了极其严谨的 **Design Tokens (设计变量)** 架构。所有的尺寸、颜色、排版和动效，均不可在代码中写死硬编码 (Hardcode)，必须严格引用以下 Token。

---

## 🎨 1. 色彩与材质系统 (Color & Material Tokens)

所有的色彩必须建立在 `oklch` 或 `rgba` 空间上以支持极致的高光和半透明混合。绝对禁止使用 `#000` 或 `#FFF` 作为纯大面积色块。

### 1.1 基础环境色 (Environment)
*空间的基础深度，决定了整个 App 的氛围。*
*   `--color-env-void`: `#05070A` (极深蓝灰底色，RGB: 5, 7, 10)
*   `--color-env-glow-primary`: `rgba(0, 240, 255, 0.08)` (用于左上角全局光晕)
*   `--color-env-glow-ai`: `rgba(181, 52, 255, 0.06)` (用于右下角全局光晕)

### 1.2 玻璃表面材质 (Glass Surfaces)
*基于 100% 黑色或白色的极低透明度，配合强烈的背景模糊产生。*
*   `--surface-100`: `rgba(255, 255, 255, 0.015)` + `backdrop-filter: blur(12px)` (适用: 底层大卡片背景)
*   `--surface-200`: `rgba(255, 255, 255, 0.03)` + `backdrop-filter: blur(24px)` (适用: 标准面板、Bento Box)
*   `--surface-300`: `rgba(255, 255, 255, 0.06)` + `backdrop-filter: blur(32px)` (适用: 悬浮窗、右侧滑出抽屉、下拉菜单)
*   `--surface-400`: `rgba(255, 255, 255, 0.12)` + `backdrop-filter: blur(48px)` (适用: 弹窗 Modal、最高层级通知)

### 1.3 描边系统 (Borders & Hairlines)
*完全抛弃实线，全部采用 Alpha 通道以适应底层颜色。*
*   `--border-subtle`: `1px solid rgba(255, 255, 255, 0.04)` (分割线)
*   `--border-default`: `1px solid rgba(255, 255, 255, 0.08)` (卡片边框)
*   `--border-strong`: `1px solid rgba(255, 255, 255, 0.16)` (输入框边框)
*   `--border-glow-primary`: `1px solid rgba(0, 240, 255, 0.4)` (聚焦状态边框)

### 1.4 文本颜色 (Text Typography Colors)
*   `--text-display`: `rgba(255, 255, 255, 1)` (绝对高亮，仅大标题)
*   `--text-primary`: `rgba(255, 255, 255, 0.85)` (正文主力，避免 100% 纯白刺眼)
*   `--text-secondary`: `rgba(255, 255, 255, 0.55)` (副文本，次要信息)
*   `--text-tertiary`: `rgba(255, 255, 255, 0.35)` (极弱信息，占位符)
*   `--text-inverse`: `rgba(0, 0, 0, 0.9)` (当背景色极亮，如主按钮为亮色时使用)

### 1.5 语义交互色 (Semantic & Accent)
*   **Brand Primary (极光青)**
    *   Base: `#00F0FF`
    *   Hover: `#4DFFFF`
    *   Active/Pressed: `#00C4D1`
*   **AI Spark (赛博紫)**
    *   Base: `#B534FF`
    *   Gradient (AI专属大招): `linear-gradient(135deg, #00F0FF 0%, #B534FF 100%)`
*   **Semantic Feedback**
    *   Success (Emerald): Base `#10B981`, Glow: `rgba(16, 185, 129, 0.15)`
    *   Warning (Amber): Base `#F59E0B`, Glow: `rgba(245, 158, 11, 0.15)`
    *   Danger (Rose): Base `#E11D48`, Glow: `rgba(225, 29, 72, 0.15)`

---

## 📏 2. 空间、网格与布局规范 (Spacing & Grid)

建立以 `4px` 为基础乘数的绝对比例尺 (Baseline Grid)。

### 2.1 间距系统 (Spacing Scale)
*   `--space-0.5`: `2px` (仅用于极细微调整)
*   `--space-1`: `4px` (图标与文字间距)
*   `--space-2`: `8px` (组件内部小间距)
*   `--space-3`: `12px`
*   `--space-4`: `16px` (移动端标准外边距，卡片内边距)
*   `--space-6`: `24px` (桌面端组件间距)
*   `--space-8`: `32px` (大区块间距)
*   `--space-12`: `48px` (章节间距)
*   `--space-16`: `64px` (页面极端留白)

### 2.2 全局响应式网格 (Global Responsive Grid)
*所有的 Dashboard 和列表页必须受限于此网格，不直接写具体像素。*
*   **Mobile (< 768px)**: 4 Columns, Gutter: `16px`, Margin: `16px`
*   **Tablet (768px - 1024px)**: 8 Columns, Gutter: `24px`, Margin: `32px`
*   **Desktop (> 1024px)**: 12 Columns, Gutter: `24px`, Max-Width: `1440px`, Center-Aligned.

### 2.3 圆角系统 (Border Radius)
*配合 Glassmorphism，必须采用较大的圆角以体现流体感。*
*   `--radius-sm`: `6px` (复选框，极小标签)
*   `--radius-md`: `12px` (标准按钮，输入框，Tooltip)
*   `--radius-lg`: `16px` (内嵌卡片，小型弹窗)
*   `--radius-xl`: `24px` (外部大容器，主 Modal 面板)
*   `--radius-pill`: `9999px` (Omnibar，悬浮 Dock，Tag)

---

## ✍️ 3. 排版系统规范 (Typography System)

精确定义每一层级的具体参数。基于 1.25 的指数放缩比。

### 3.1 字体族群 (Font Families)
*   `--font-heading`: `'Outfit', 'Plus Jakarta Sans', sans-serif` (专供数字与标题)
*   `--font-body`: `'Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', Roboto, sans-serif`
*   `--font-mono`: `'JetBrains Mono', 'Fira Code', 'SF Mono', monospace` (专供工具调用与代码区块)

### 3.2 字阶规范表 (Type Scale Table)
*   **Display 1** (极巨文字，如总分)
    *   Size: `72px` (4.5rem), Line-Height: `1.0`, Weight: `300`, Tracking: `-0.03em`
*   **Display 2** (大页面主标题)
    *   Size: `48px` (3rem), Line-Height: `1.1`, Weight: `400`, Tracking: `-0.02em`
*   **Heading 1** (模块主标题)
    *   Size: `32px` (2rem), Line-Height: `1.2`, Weight: `500`, Tracking: `-0.01em`
*   **Heading 2** (卡片标题)
    *   Size: `24px` (1.5rem), Line-Height: `1.3`, Weight: `500`, Tracking: `0`
*   **Heading 3** (列表小标题)
    *   Size: `18px` (1.125rem), Line-Height: `1.4`, Weight: `600`, Tracking: `0`
*   **Body Large** (引入段落)
    *   Size: `16px` (1rem), Line-Height: `1.6`, Weight: `400`, Tracking: `0.01em`
*   **Body Base** (常规正文主力)
    *   Size: `15px` (0.9375rem), Line-Height: `1.6`, Weight: `400`, Tracking: `0.01em`
*   **Caption** (脚注，标签)
    *   Size: `13px` (0.8125rem), Line-Height: `1.5`, Weight: `500`, Tracking: `0.03em`
*   **Mono Micro** (工具日志专用)
    *   Size: `11px` 或 `12px`, Line-Height: `1.5`, Weight: `400`, Tracking: `0`

---

## 🦋 4. 层级深度与阴影特效 (Elevation & Glow)

完全舍弃黑色的 `box-shadow`。在暗色的深空背景中，黑色阴影是不可见的。深度的唯一呈现方式是：**光照的高光 + 背景的模糊 + 尺寸的变化**。

### 4.1 光晕与环境光 (Glows & Drop Shadows)
*   `--shadow-glow-sm`: `0 0 12px 0 rgba(0, 240, 255, 0.1)` (适用: Hover 按钮的高光)
*   `--shadow-glow-md`: `0 0 24px 0 rgba(0, 240, 255, 0.15)` (适用: Active 输入框，警告块)
*   `--shadow-glow-lg`: `0 0 48px 0 rgba(181, 52, 255, 0.2)` (适用: AI 强力生成状态下的容器)
*   `--shadow-elevation-high`: `0 24px 48px -12px rgba(0,0,0,0.5), inset 0 1px 0 0 rgba(255,255,255,0.1)` (适用: 悬浮全局菜单，必须自带顶部 1px 高光内阴影)

### 4.2 Z-Index 层级映射 (Z-Stack)
必须使用语义化变量，绝对禁止业务代码中出现 `z-index: 9999`。
*   `--z-base`: `0` (底层画布)
*   `--z-elevated`: `10` (Bento 卡片)
*   `--z-sticky`: `30` (吸顶元素，固定表头)
*   `--z-dock`: `40` (悬浮 Dock，Omnibar)
*   `--z-overlay`: `50` (抽屉浮层遮罩)
*   `--z-drawer`: `60` (侧边抽屉面板)
*   `--z-modal`: `70` (屏幕中央弹窗)
*   `--z-toast`: `100` (最高优先级全局通知消息)

---

## 🎬 5. 动效物理规范 (Animation Physics)

严禁一切拖沓的线性动画。动效必须响应迅速 (Snappy)，收尾平滑 (Smooth)，具有顶级 App 的回弹质感。

### 5.1 基础持续时间 (Durations)
*   `--dur-fast`: `150ms` (状态切换，颜色 Hover 渐变)
*   `--dur-base`: `250ms` (小型弹窗，尺寸轻微改变)
*   `--dur-slow`: `400ms` (页面大面积滑入，路由过渡)

### 5.2 运动曲线 (Easing Curves - CSS)
*仅用于颜色渐变、透明度等无法使用弹簧系统的简单 CSS 动画。*
*   `--ease-in-out`: `cubic-bezier(0.4, 0, 0.2, 1)` (系统标准平滑)
*   `--ease-out-back`: `cubic-bezier(0.34, 1.56, 0.64, 1)` (弹出时带轻微超调)
*   `--ease-emphasized`: `cubic-bezier(0.2, 0, 0, 1)` (极速启动，极其缓慢减速，用于超大面积进场)

### 5.3 物理弹簧参数 (Spring Physics - Framer Motion)
*凡涉及位移 (x, y)、缩放 (scale) 与宽高变化，全部强制使用 Framer Motion 的 Spring 参数！*
1.  **Snappy (极速回弹)**
    *   `stiffness: 400, damping: 25`
    *   *用途*: Dock 图标缩放，按钮点击下压，单选框切换。感觉像物理键盘一样干脆。
2.  **Smooth (丝滑过渡)**
    *   `stiffness: 250, damping: 30`
    *   *用途*: Omnibar 宽度伸展，Bento 卡片位置重排 (Layout Animations)。
3.  **Gentle (柔和宽缓)**
    *   `stiffness: 100, damping: 20`
    *   *用途*: 全局页面的大规模进出场，右侧超大抽屉的滑入。没有突兀的抖动，只有如丝般的滑入。

---

## 🛠 6. 核心场景：对话界面与工具调用规范 (Chat UI & Tool Calling Specs)

对话界面（Chat UI）是系统与用户交互的灵魂。针对 AI 正在“思考”与“调用外部工具 (Tool Calling)”的中间状态，必须通过极具科技感的排版与动画，向用户传递“高级智能感”与执行的高透明度。

### 6.1 消息气泡基础结构 (Message Bubbles)
*   **用户消息 (User Bubble)**
    *   **排版**: 紧凑，右对齐。
    *   **材质**: 采用高一级的 `--surface-300` 配合微弱的极光青光晕，以区别于环境背景，体现用户主动输入。
    *   **圆角不对称**: 右下角为较锐利的 `--radius-sm`，其余三个角采用圆润的 `--radius-xl`。
*   **AI 回复 (Assistant Stream)**
    *   **排版**: 左对齐，直接渲染在基础流体空间中。
    *   **材质**: **完全移除传统的气泡边框背景**。文字直接漂浮输出在底板上，但流式输出的光标必须使用明亮的 `--color-env-glow-ai` 色块，体现“正在打印”。

### 6.2 工具调用卡片状态机 (Tool Call States)
工具调用卡片 (Tool Card) 是内嵌在 AI 回复信息流中的结构化玻璃区块（Glass Blocks）。

1.  **运行中状态 (Executing)**
    *   **视觉特征**: 卡片边框呈现循环流动的 `--border-glow-primary` (赛博紫与极光青交替闪烁的流光渐变效果，跑马灯式循环)。
    *   **排版特征**: 极简的一行模式。最左侧为一直旋转的细腻微小 Spinner (线宽极细 1.5px)，中间紧跟着执行状态文本（例如 `Reading codebase...`），字体**强制要求使用等宽字体 `--font-mono`**，字号 `--text-mono-micro` (`12px` 或 `11px`)，体现极客氛围。
2.  **成功完成状态 (Success & Collapsed)**
    *   **视觉特征**: 边框流光立刻熄灭，材质降级为极暗且低调的 `--surface-100`。左侧图标变为带有极弱绿光的 Checkmark (成功绿色 `#10B981` 叠加透明度)。
    *   **展开交互**: 默认收起为小巧的标签状态（如 `✓ Searched web [0.8s]`）。Hover 时卡片具有 `--shadow-glow-sm` 呼吸反馈，提示可点击展开查看运行的 JSON 详情。
3.  **异常中断状态 (Error)**
    *   **视觉特征**: 边框瞬间闪烁两次后，定格在红色的微弱暗光中 (`rgba(225, 29, 72, 0.4)`)。
    *   **文本特征**: 文本转为警示红，高亮显示报错堆栈，并提供一个精致的“Retry（重试）”悬浮操作按钮。

### 6.3 工具详情展示面板 (Tool Payload Hacker Panel)
当用户好奇并点击展开某个完成的工具卡片时，内部展开的界面必须像一台“高级终端机 (Hacker Terminal)”。
*   **深渊对比材质**: 内部详情容器必须使用全系统最暗的底板 `rgba(0,0,0,0.4)`，与外部的浅灰玻璃拟态形成强烈的黑白/虚实对比。
*   **硬核数据排版 (JSON/Args)**:
    *   字体：严格采用等宽字体 (JetBrains Mono 等)。
    *   语法高亮 (Syntax Highlighting)：Key 名使用极光青 `#00F0FF`，Value 值（字符串）使用高对比的浅黄色或纯亮白色，数字使用浅紫色。
    *   字号：极小（`11px`），由于使用了等宽字体，即使再小的文字也能清晰辨认，这种密集的代码字符能瞬间拔高界面的“专业极客感”。
*   **流畅展出动画**: 面板向下展开严禁瞬间硬切生硬闪现。必须使用 Framer Motion 的 `height: "auto"` 过渡，配合 `Smooth` 级别的弹簧参数，像高级抽屉一样被缓缓拉开。

---

## 📖 7. 核心业务场景特写 (Core Business Scenario Highlights)

除通用组件外，针对系统中最重要的两大业务场景（阅读资料与试卷答题），我们定义了专属的“高阶沉浸”设计模式，彻底打破传统表单或平铺文档的局限。

### 7.1 阅读与自学资料生成模式 (Reading & Material Generation)
此场景的核心使命是**“极简降噪阅读”**与**“伴随式 AI 生成联动”**。

*   **剧院级降噪阅读区 (Theater Reading Mode)**
    *   **视差背景 (Parallax Background)**: 当用户进入深度阅读模式时，全局 Dock 和 Omnibar 会通过过渡动画自动降低透明度至 `20%`（甚至完全滑出屏幕）。底层抛弃一切边框，变为纯粹的 `--color-env-void` 深空色，犹如剧院熄灯，消除一切光源干扰。
    *   **杂志级排版 (Editorial Typography)**: 阅读区底板使用极其克制的 `--surface-100`，**最大行宽被严格限定为 `720px`**（人类工程学最佳护眼阅读宽度）。正文字体 `--font-body` 字号放大至 `16px` 或 `17px`，行高舒展至 `1.8`，字体颜色采用极度护眼柔和的 `--text-secondary` (`rgba(255,255,255,0.7)`)，绝对禁止用纯白刺眼高光。
*   **伴随式 AI 生成引擎 (Sidecar AI Generator)**
    *   **玻璃侧翼滑入 (Glass Wing)**: 当用户选中一段资料请求“AI解析”或“生成扩展资料”时，不再使用低级的中央弹窗。屏幕右侧会通过 `--ease-emphasized` 曲线，无缝滑入一个极高模糊度 (`blur(48px)`) 的玻璃侧翼面板。
    *   **脉冲高亮情感联动 (Pulse Syncing)**: 侧面板在全速生成解析时（面板边缘带有赛博紫流光流动），原文中被选中的触发段落必须**同步产生极低频率的呼吸状微光高亮** (`rgba(181, 52, 255, 0.15)`)，就像两条神经元在连通一样，让用户深刻感知到“AI 正在基于此处文字进行思考”。

### 7.2 无界试卷答题画板 (Borderless Exam Canvas)
传统的“白纸黑字铺在灰色背景上”的答卷界面过于复古死板，我们将“答题”升维至**空间计算级别的无穷画布 (Infinite Space Canvas)** 体验。

*   **全景暗场点阵星空 (Dot-Grid Space Array)**
    *   **空间纹理**: 移除传统的纯色容器。整个画板容器背景使用 CSS `radial-gradient` 绘制间距为 `24px`、透明度极低 (`rgba(255,255,255,0.05)`) 的精密微观点阵 (Dot-Grid)。这不仅为无极缩放 (Zoom) 和拖拽 (Pan) 提供了天然的物理参照物，更让做题体验犹如漂浮在星空工作台上。
*   **悬浮流体题卡与景深 (Floating Question Cards & Depth)**
    *   **题卡实体**: 每道题目不再是连在一起的长文，而是一张独立的独立玻璃便当盒（采用 `--surface-200`，具有丰满的 `--radius-xl` 24px 圆角），在画板上错落排布或以单瀑布流形式呈现。
    *   **作答焦点聚光灯 (Focus Depth Spotlight)**: 当用户点击某道题进入作答状态时，这道题的卡片通过 Framer Motion 的 Spring 动画迅速浮起并放大至 `scale(1.02)`，同时**其余所有未激活的题目卡片透明度瞬间衰减至 `40%` 且叠加高斯模糊 (`blur(4px)`)**。利用这种强烈的**人为景深 (Depth of Field)** 剥离干扰，强制聚拢专注力。
*   **磁吸式手写与工具坞 (Magnetic Tools Dock)**
    *   **阻尼工具栏**: 放弃固定的顶部菜单栏，提供包含笔刷、橡皮、公式键盘等工具的小型悬浮胶囊工具坞。它必须具备物理惯性——当用户快速拖拽画板视角时，工具坞会带有微小延迟的“弹簧阻尼缓冲跟随”，像太空舱里的失重物体。
    *   **能量绘图笔迹 (Ink Rendering)**: 用户输入的文本、手写标注，或者是 AI 自动填写的批改痕迹，必须叠加极微弱的发光特效。例如：红色的 AI 批改字迹带有 `text-shadow: 0 0 12px rgba(225, 29, 72, 0.4)`，彻底摆脱死板的像素字，还原出一种科幻的“能量绘图”特质。
