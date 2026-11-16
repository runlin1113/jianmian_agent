"""Package the architecture analysis; never changes application sources."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import re
from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT=Path(__file__).resolve().parents[2]
RESEARCH=Path(__file__).resolve().parent
DOCS=ROOT/'docs'
DESIGN=DOCS/'superpowers/specs/2026-11-15-jianmian-architecture-design.md'
REPORT=RESEARCH/'open-source-research.md'
ASSETS=DOCS/'assets'
ASSETS.mkdir(parents=True,exist_ok=True)

def fingerprint(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def source_manifest():
    repos={}
    for bucket in ['upstream','verified','official','branch_sources']:
        base=RESEARCH/bucket
        if not base.exists(): continue
        for meta in sorted(base.glob('*/metadata.json')):
            data=json.loads(meta.read_text(encoding='utf-8-sig'))
            repo=data['repo']
            record=repos.setdefault(repo,{'repo':repo,'url':'https://github.com/'+repo,'observed_commits':[],'files':[]})
            commit=data.get('commit') or data.get('ref')
            if commit and re.fullmatch('[0-9a-f]{40}',commit) and commit not in record['observed_commits']:
                record['observed_commits'].append(commit)
            for file in meta.parent.iterdir():
                if file.name=='metadata.json' or file.name=='tree.json' or not file.is_file(): continue
                if file.name not in ['README.md','LICENSE','LICENSE.md','LICENSE.txt','NOTICE']: continue
                files=data.get('files',{})
                entry=files.get(file.name,{}) if isinstance(files,dict) else next((x for x in files if x.get('path')==file.name),{})
                record['files'].append({'path':str(file.relative_to(ROOT)).replace('\\','/'),'source_url':entry.get('url'),'retrieved_at':data.get('retrieved_at'),'sha256':fingerprint(file),'reference_type':'branch' if bucket=='branch_sources' else 'recorded_ref'})
    manifest={'date':'2026-11-15','generated_at':datetime.now(timezone.utc).isoformat(),'method':'Public repository metadata, Git refs, README and LICENSE snapshots; no upstream application execution. Branch snapshots are not asserted identical to independently observed commits.','repos':list(repos.values()),'local_inputs':[{'path':str(p.relative_to(ROOT)),'sha256':fingerprint(p)} for p in sorted(ROOT.glob('*.docx'))]}
    (RESEARCH/'source-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest

def diagram():
    im=Image.new('RGB',(2200,1440),'#f5f8fc')
    d=ImageDraw.Draw(im)
    regular=r'C:\Windows\Fonts\msyh.ttc'
    bold=r'C:\Windows\Fonts\msyhbd.ttc'
    def font(size,strong=False): return ImageFont.truetype(bold if strong else regular,size)
    def center(text,x,y,w,size=32,color='#24415e',strong=False):
        f=font(size,strong); box=d.textbbox((0,0),text,font=f)
        d.text((x+(w-(box[2]-box[0]))/2,y),text,font=f,fill=color)
    def box(bounds,title,lines,accent='#14365a',fill='#ffffff'):
        x,y,x2,y2=bounds
        d.rounded_rectangle(bounds,radius=24,fill=fill,outline='#d6e0eb',width=3)
        d.rounded_rectangle((x,y,x2,y+12),radius=6,fill=accent)
        center(title,x,y+35,x2-x,36,accent,True)
        for i,line in enumerate(lines): center(line,x,y+108+i*52,x2-x,29)
    def arrow(points,color='#6b8299',width=6):
        d.line(points,fill=color,width=width,joint='curve')
        x,y=points[-1]; px,py=points[-2]
        if abs(x-px)>abs(y-py):
            sign=1 if x>px else -1
            d.polygon([(x,y),(x-sign*20,y-12),(x-sign*20,y+12)],fill=color)
        else:
            sign=1 if y>py else -1
            d.polygon([(x,y),(x-12,y-sign*20),(x+12,y-sign*20)],fill=color)
    center('简面智能体 · 推荐架构',0,38,2200,53,'#14365a',True)
    center('保留编辑与打印能力，让智能体通过可审阅的修改提案协作',0,112,2200,29)
    box((440,200,1760,380),'用户入口',['表单编辑  /  对话构建  /  导入旧简历  /  模拟面试'])
    box((80,490,1020,830),'浏览器：简历编辑内核',['八类模块 · 两套版式 · 六套主题','统一命令 · 字段校验 · 版本与撤销','真实 A4 测量 · 浏览器打印 PDF'])
    box((1180,490,2120,830),'Python：FastAPI + LangGraph',['会话与预算 → 意图与工具计划','字段／事实校验 → 修改提案与事件','任务状态有期限，长期记忆默认在本地'])
    arrow([(770,380),(550,490)])
    arrow([(1430,380),(1650,490)])
    arrow([(1020,590),(1180,590)])
    center('指令与片段',1010,540,180,23)
    arrow([(1180,750),(1020,750)],'#118777')
    center('提案与事件',1010,775,180,23,'#118777')
    box((80,940,1020,1150),'浏览器本地存储',['简历 · 用户事实／偏好 · 历史 · 头像'],accent='#118777',fill='#effaf6')
    arrow([(550,830),(550,940)])
    for x,title,lines in [(1180,'模型适配',['DeepSeek','本地模型']), (1500,'解析适配',['PDF / DOCX','OCR']), (1820,'岗位与联网',['公共岗位库','受控搜索'])]:
        box((x,940,x+300,1180),title,lines)
    arrow([(1650,830),(1650,885),(1330,885),(1330,940)])
    arrow([(1650,885),(1650,940)])
    arrow([(1650,885),(1970,885),(1970,940)])
    d.rounded_rectangle((80,1245,2120,1350),radius=24,fill='#14365a')
    center('用户确认 → 版本检查 → 本地事务应用 → 确定性撤销',80,1275,2040,36,'#ffffff',True)
    center('AI 调用只发送用户授权的必要片段；云模型调用并不等于数据不出本机。',0,1380,2200,25,'#5c7084')
    path=ASSETS/'jianmian-architecture.png'
    im.save(path)
    return path

def inline(paragraph,text,size=None,bold=False):
    text=re.sub(r'\[([^\]]+)\]\(([^)]+)\)',r'\1（\2）',text)
    for i,part in enumerate(re.split(r'(\*\*.*?\*\*|`[^`]+`)',text)):
        if not part: continue
        emphasis=part.startswith('**') and part.endswith('**')
        code=part.startswith('`') and part.endswith('`')
        content=part[2:-2] if emphasis else part[1:-1] if code else part
        r=paragraph.add_run(content)
        r.bold=bold or emphasis
        if size: r.font.size=Pt(size)
        if code: r.font.name='Consolas';r.font.color.rgb=RGBColor.from_string('28435D')

def make_doc(title,subtitle,markdown,path,figure=None):
    doc=Document()
    section=doc.sections[0]
    section.page_width=Cm(21);section.page_height=Cm(29.7)
    section.top_margin=Cm(1.8);section.bottom_margin=Cm(1.8)
    section.left_margin=Cm(1.8);section.right_margin=Cm(1.8)
    normal=doc.styles['Normal']
    normal.font.name='Microsoft YaHei';normal.font.size=Pt(10)
    normal._element.rPr.rFonts.set(qn('w:eastAsia'),'微软雅黑')
    normal.paragraph_format.space_after=Pt(5)
    normal.paragraph_format.line_spacing=1.22
    for n,size in [('Title',27),('Heading 1',18),('Heading 2',14),('Heading 3',11)]:
        st=doc.styles[n];st.font.name='Microsoft YaHei';st.font.size=Pt(size)
        st._element.rPr.rFonts.set(qn('w:eastAsia'),'微软雅黑')
        st.font.color.rgb=RGBColor.from_string('14365A')
        st.paragraph_format.keep_with_next=True
    header=section.header.paragraphs[0]
    header.text='简面 Jianmian Studio  |  架构研究  |  2026-11-15'
    header.style=doc.styles['Caption']
    footer=section.footer.paragraphs[0];footer.alignment=2
    footer.add_run('第 ')
    field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');footer._p.append(field)
    footer.add_run(' 页')
    doc.add_paragraph(title,'Title')
    doc.add_paragraph(subtitle,'Subtitle')
    doc.add_paragraph('版本：设计建议稿 · 2026-11-15\n依据：项目说明书、现有平台源码、公开开源仓库资料\n范围：架构与研究交付；未修改现有应用源码。')
    if figure:
        doc.add_picture(str(figure),width=Cm(17.3))
        p=doc.add_paragraph('图 1  推荐架构概览','Caption')
        p.paragraph_format.keep_with_next=False
    doc.add_page_break()
    lines=markdown.splitlines();i=0
    while i<len(lines):
        line=lines[i]
        if line.startswith('# '): i+=1;continue
        if not line.strip():i+=1;continue
        if line.startswith('```'):
            kind=line[3:].strip();block=[];i+=1
            while i<len(lines) and not lines[i].startswith('```'):
                block.append(lines[i]);i+=1
            if kind=='mermaid':
                if 'flowchart LR' in '\n'.join(block):
                    doc.add_paragraph('流程：输入校验 → 上下文 → 意图与计划 → 权限／预算 → 工具 → 校验 → 提案 → 用户确认 → 本地应用。需要素材时进入澄清。','Caption')
                else:
                    doc.add_paragraph('架构图见图 1；可维护的 Mermaid 原图保留在 Markdown 版本中。','Caption')
            else:
                p=doc.add_paragraph();p.paragraph_format.space_after=Pt(8)
                for j,b in enumerate(block):
                    r=p.add_run(b+('\n' if j<len(block)-1 else ''));r.font.name='Consolas';r.font.size=Pt(8)
                    r._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'微软雅黑')
            i+=1;continue
        if line.startswith('|'):
            rows=[]
            while i<len(lines) and lines[i].startswith('|'):
                cells=[s.strip() for s in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-+:?',c or '') for c in cells): rows.append(cells)
                i+=1
            n=max(map(len,rows));table=doc.add_table(rows=1,cols=n);table.style='Light Shading Accent 1'
            table.autofit=False
            for col in table.columns: col.width=Cm(17.3/n)
            for ri,row in enumerate(rows):
                cells=table.rows[0].cells if ri==0 else table.add_row().cells
                for ci,value in enumerate(row): inline(cells[ci].paragraphs[0],value,size=8.5,bold=ri==0)
                if ri==0:
                    prop=table.rows[0]._tr.get_or_add_trPr();repeat=OxmlElement('w:tblHeader');prop.append(repeat)
                else:
                    prop=table.rows[-1]._tr.get_or_add_trPr();cant=OxmlElement('w:cantSplit');prop.append(cant)
            doc.add_paragraph()
            continue
        if line.startswith('### '):
            doc.add_paragraph(line[4:],'Heading 2')
        elif line.startswith('## '):
            doc.add_paragraph(line[3:],'Heading 1')
        elif line.startswith('- '):
            inline(doc.add_paragraph(style='List Bullet'),line[2:])
        elif re.match(r'^\d+\. ',line):
            inline(doc.add_paragraph(style='List Number'),re.sub(r'^\d+\. ','',line))
        else: inline(doc.add_paragraph(),line)
        i+=1
    doc.core_properties.title=title
    doc.core_properties.subject='基于现有简面平台的可维护、可扩展、安全架构'
    doc.core_properties.author='简面项目架构研究'
    doc.save(path)
    check=Document(path)
    assert len(check.paragraphs)>20 and len(check.tables)>0
    return {'file':str(path.relative_to(ROOT)),'paragraphs':len(check.paragraphs),'tables':len(check.tables),'bytes':path.stat().st_size}

manifest=source_manifest()
figure=diagram()
result=[]
result.append(make_doc('简面智能体架构设计方案','本地优先 · 可审阅修改 · 事实证据 · 真实版面反馈',DESIGN.read_text(encoding='utf-8'),DOCS/'简面智能体架构设计方案.docx',figure))
result.append(make_doc('简面智能体开源项目调研','框架选择 · 简历产品对照 · 解析工具 · 许可证',REPORT.read_text(encoding='utf-8'),DOCS/'简面智能体开源项目调研.docx'))
design=DESIGN.read_text(encoding='utf-8')
assert all(('R'+str(i)) in design for i in range(1,8))
assert all(('M'+str(i)) in design for i in range(1,15))
for block in re.findall(r'```json\n(.*?)\n```',design,re.S):json.loads(block)
for p in [DESIGN,REPORT]:
    assert '\ufffd' not in p.read_text(encoding='utf-8')
    assert not re.search(r'\b(TODO|TBD)\b',p.read_text(encoding='utf-8'))
verified=[r for r in manifest['repos'] if r['files']]
validation={'artifacts':result,'repositories_with_saved_files':len(verified),'repositories_considered':len(manifest['repos']),'requirements_checked':'R1-R7 and M1-M14 present; illustrative JSON parses','limitations':'DOCX package and structure checked; no Word/LibreOffice pagination rendering available; application runtime not modified or tested.'}
(RESEARCH/'deliverable-validation.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(validation,ensure_ascii=True,indent=2))
