"""Build a public working-paper PDF in the supplied single-column academic style."""
from pathlib import Path
from html import escape
import re
from docx import Document
from docx.table import Table as WordTable
from docx.text.paragraph import Paragraph as WordParagraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether, PageBreak
from reportlab.lib import colors

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / 'agent_safety_exceptions.pdf'
SOURCE = HERE / 'source_manuscript.docx'

def clean(s):
    return s.replace('\u2013','-').replace('\u2014','-').replace('\u2011','-').replace('\u2019',"'").replace('\u2265','>=').replace('ć','c').replace('đ','d')

normal = ParagraphStyle('Body',fontName='Times-Roman',fontSize=10,leading=11.6,spaceAfter=6,alignment=TA_JUSTIFY)
abstract = ParagraphStyle('Abstract',parent=normal,leftIndent=24,rightIndent=24)
heading = ParagraphStyle('Heading',fontName='Times-Bold',fontSize=12,leading=14,spaceBefore=10,spaceAfter=5,keepWithNext=True)
subheading = ParagraphStyle('Subheading',parent=heading,fontSize=10.5,leading=12.5,spaceBefore=7)
center = ParagraphStyle('Center',parent=normal,alignment=TA_CENTER)
small = ParagraphStyle('Small',parent=normal,fontSize=8.2,leading=9.5,alignment=0)
cell = ParagraphStyle('Cell',parent=normal,fontSize=8.5,leading=10,spaceAfter=0,alignment=0)

def markup(p):
    out=[]
    for elem in p._p:
        tag=elem.tag.split('}')[-1]
        txt=''.join(elem.itertext()) if False else ''.join(t.text or '' for t in elem.iter() if t.tag.endswith('}t'))
        if not txt: continue
        txt=escape(clean(txt))
        if tag=='hyperlink':
            rid=elem.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
            if rid and rid in p.part.rels:
                url=p.part.rels[rid].target_ref
                txt='<link href="'+escape(url,quote=True)+'" color="#164a70">'+txt+'</link>'
        out.append(txt)
    return ''.join(out)

major={'Motivation and research question','Operational model and threat boundary','Experimental design and evidence separation',
       'Controlled policy results','Measured capability','Post hoc requirement coverage and runtime hardening',
       'Related work and interpretation','Limitations and remaining validation','Conclusion','Reproducibility','References'}
story=[HRFlowable(width='100%',thickness=3,color=colors.black),Spacer(1,12),
       Paragraph('Can AI Agents Manufacture Their Own Safety Exceptions?',ParagraphStyle('Title',parent=center,fontName='Times-Bold',fontSize=17,leading=19)),
       Spacer(1,9),HRFlowable(width='100%',thickness=.5,color=colors.black),Spacer(1,18),
       Paragraph('<b>Amornchot Singh</b>',center),
       Paragraph('Provenance and recovery requirements for conditional agent permissions',center),
       Paragraph('Working manuscript - 18 October 2026',center),Spacer(1,12)]
doc=Document(SOURCE); section=0; current=''; references=False
for element in doc.element.body:
    tag=element.tag.split('}')[-1]
    if tag=='p':
        p=WordParagraph(element,doc); text=p.text.strip()
        if not text or p.style.name in {'Title','Subtitle'} or text.startswith('Amornchot Singh |'): continue
        if p.style.name.startswith('Heading'):
            current=text
            if text=='Abstract': story.append(Paragraph('Abstract',ParagraphStyle('AbsHeading',parent=heading,alignment=TA_CENTER)))
            elif text in major:
                if text=='References': references=True; label=text; story.append(PageBreak())
                else: section+=1;label=f'{section}  {text}'
                story.append(Paragraph(escape(label),heading))
            else: story.append(Paragraph(escape(text),subheading))
            continue
        text=markup(p)
        if current=='Reproducibility':
            text += ' The public release contains the corrected capability runs and scripted comparisons; excluded historical cohorts remain outside this release. An additional external-model capability runner is implemented but has not made paid model calls.'
        if text.startswith('Table 5.'):
            text += ' Since that study snapshot, the external capability runner added 14 offline checks; all 331 project checks now pass. This is software validation, not new model evidence.'
        story.append(Paragraph(text,abstract if current=='Abstract' else small if references or text.startswith('Table ') else normal))
    elif tag=='tbl':
        t=WordTable(element,doc)
        rows=[[Paragraph(('<b>'+escape(clean(c.text))+'</b>') if i==0 else escape(clean(c.text)),cell) for c in r.cells] for i,r in enumerate(t.rows)]
        n=len(rows[0]); widths={2:[106,290],3:[192,102,102],4:[112,92,100,92],5:[94,94,61,68,79]}[n]
        table=Table(rows,colWidths=widths,repeatRows=1,hAlign='CENTER')
        table.setStyle(TableStyle([('LINEABOVE',(0,0),(-1,0),.8,colors.black),('LINEBELOW',(0,0),(-1,0),.4,colors.black),
                                  ('LINEBELOW',(0,-1),(-1,-1),.8,colors.black),('VALIGN',(0,0),(-1,-1),'TOP'),
                                  ('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4),
                                  ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
        story.extend([table,Spacer(1,8)])

# Keep compact tables and their following captions together across page breaks.
grouped=[]; i=0
while i<len(story):
    if isinstance(story[i],Table):
        group=[story[i]];i+=1
        if grouped and isinstance(grouped[-1],Paragraph) and grouped[-1].style.name in {'Heading','Subheading'}:
            group.insert(0,grouped.pop())
        if i<len(story) and isinstance(story[i],Spacer): group.append(story[i]);i+=1
        if i<len(story) and isinstance(story[i],Paragraph) and story[i].text.startswith('Table '):
            group.append(story[i]);i+=1
        grouped.append(KeepTogether(group))
    else: grouped.append(story[i]);i+=1
story=grouped

def footer(c,d):
    c.saveState();c.setFont('Times-Roman',8)
    c.drawCentredString(306,37,str(d.page))
    if d.page==1: c.drawCentredString(306,49,'Working manuscript. Not accepted or published in conference proceedings.')
    c.restoreState()
SimpleDocTemplate(str(OUTPUT),pagesize=(612,792),leftMargin=108,rightMargin=108,topMargin=65,bottomMargin=62,
                  title='Can AI Agents Manufacture Their Own Safety Exceptions?',author='Amornchot Singh').build(story,onFirstPage=footer,onLaterPages=footer)
print(OUTPUT)
