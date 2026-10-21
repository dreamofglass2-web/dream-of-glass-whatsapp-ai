"""Private in-memory Hebrew quote PDF from calculator-authorized offer data."""
from sales_items import offer_height_note
from pathlib import Path
from io import BytesIO
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
from bidi.algorithm import get_display
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader

ASSETS=Path(__file__).with_name('quote_assets')

def create_quote_pdf(offer, customer, issued_at=None):
    items=offer.get('items') or []
    if not items or len(items)>3:
        raise ValueError('Incomplete offer')
    amounts=[Decimal(str(item['amount_ils_pre_vat'])) for item in items]
    subtotal=sum(amounts)
    if any(not n.is_finite() or n<=0 for n in amounts) or subtotal!=Decimal(str(offer['amount_ils_pre_vat'])):
        raise ValueError('Offer total mismatch')
    vat=(subtotal*Decimal('0.18')).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
    total=subtotal+vat
    stamp=issued_at or datetime.now(ZoneInfo('Asia/Jerusalem'))
    if isinstance(stamp,str):
        stamp=datetime.fromisoformat(stamp).astimezone(ZoneInfo('Asia/Jerusalem'))
    reference='DG-'+hashlib.sha256((str(customer.get('phone') or '')+offer['fingerprint']).encode()).hexdigest()[:10].upper()
    for name,file in [('QuoteRegular','quote-regular.ttf'),('QuoteBold','quote-bold.ttf')]:
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name,str(ASSETS/file)))
    output=BytesIO();c=canvas.Canvas(output,pagesize=(595.28,841.89))
    c.setTitle('הצעת מחיר '+reference);c.setAuthor('חלומות מזכוכית')
    def text(value,x,y,size=10,bold=False,color='black',align='right'):
        c.setFillColor(color);c.setFont('QuoteBold' if bold else 'QuoteRegular',size)
        value=get_display(str(value))
        {'right':c.drawRightString,'left':c.drawString,'center':c.drawCentredString}[align](x,y,value)
    def wrap(value,width,size=10):
        lines=[];line=''
        for word in str(value).split():
            candidate=(line+' '+word).strip()
            if line and pdfmetrics.stringWidth(get_display(candidate),'QuoteRegular',size)>width:
                lines.append(line);line=word
            else:line=candidate
        return lines+[line] if line else lines
    def footer():
        c.setFillColor('black');c.rect(0,0,596,24,fill=1,stroke=0)
        text('חלומות מזכוכית | 0508554415 | Dream.of.glass2@gmail.com',297.6,9,8,color='white',align='center')
    def header(continued=False):
        c.setFillColor('black');c.rect(0,730,596,112,fill=1,stroke=0)
        text('בס״ד',570,824,8,color='white')
        text('הצעת מחיר ראשונית',297.6,802,18,True,'white','center')
        text('מספר הצעה '+reference,297.6,780,10,color='white',align='center')
        text('תאריך '+stamp.strftime('%d/%m/%Y'),297.6,762,10,color='white',align='center')
        footer()
        return 700
    y=header()
    c.drawImage(ImageReader(str(ASSETS/'quote-logo.jpg')),460,623,width=86,height=85,preserveAspectRatio=True,mask='auto')
    text('מאת',555,605,11,True);text('חלומות מזכוכית',555,586)
    text('0508554415',555,569);text('Dream.of.glass2@gmail.com',555,552,9)
    text('עבור',270,605,11,True)
    for line in wrap(customer.get('name') or 'לקוח',220):
        text(line,270,586);y=569
    text(customer.get('phone') or '',270,569)
    y=525
    c.setFillColor('black');c.rect(40,y-25,515,25,fill=1,stroke=0)
    for label,x in [('תיאור',545),('כמות',267),('מחיר',194),('סך הכל',113)]:text(label,x,y-16,9,True,'white')
    y-=43
    for item,amount in zip(items,amounts):
        s=item['specification'];number=item['number']
        size=str(s['width_cm'])+((' על '+str(s['second_width_cm'])) if s.get('second_width_cm') else '')
        label={'1':'הראשון','2':'השני','3':'השלישי'}.get(number,number)
        product='אמבטיון' if 'אמבטיון' in str(s.get('product') or '')+str(s.get('configuration') or '') else 'מקלחון'
        desc=f"{product} {label}, {s['configuration']}, {size} ס״מ, גובה {s['height_cm']} ס״מ."
        detail=f"זכוכית {s['glass_type']}, פרזול {s['finish']}, "+', '.join(s.get('handles') or [])
        lines=wrap(desc,260,9)+wrap(detail,260,9)
        height=max(48,len(lines)*15+17)
        if y-height<290:
            c.showPage();y=header(True)-45
        for n,line in enumerate(lines):text(line,545,y-n*15,9)
        text('1',267,y,9);text(f'₪{amount:,.2f}',194,y,9);text(f'₪{amount:,.2f}',113,y,9)
        y-=height;c.setStrokeColorRGB(.84,.85,.88);c.line(40,y+10,555,y+10)
    y-=7
    for label,number in [('סך הכל לפני מע״מ',subtotal),('מע״מ 18%',vat),('סך הכל לתשלום',total)]:
        final=label=='סך הכל לתשלום'
        c.setFillColor('black' if final else '#F3F4F6');c.rect(40,y-28,245,28,fill=1,stroke=0)
        text(label,275,y-18,10,final,'white' if final else 'black')
        text(f'₪{number:,.2f}',115,y-18,10,final,'white' if final else 'black');y-=28
    y-=25
    if y<235:
        c.showPage();y=header(True)-25
    c.setFillColor('black');c.rect(40,y-24,515,24,fill=1,stroke=0)
    text('הערות ותנאים',545,y-16,10,True,'white');y-=45
    notes=[
        'המחיר כולל מדידה, הובלה והתקנה. זכוכית מחוסמת 8 מ״מ ופרזול פליז פרימיום.',
        '7 שנות אחריות על הפרזול ושנה על ההתקנה. אין אחריות על הזכוכית.',
        'זו הצעת מחיר ראשונית על בסיס הנתונים שנמסרו. המידות וההתאמה הסופיות ייבדקו בשטח.',
        offer_height_note(offer),
        'לאחר אישור ההצעה, אלירן ייצור קשר לתיאום מדידה.',
        'אישור ההצעה אינו תיאום מועד מדידה או התקנה.']
    for note in notes:
        for line in wrap(note,505,9):
            if y<55:c.showPage();y=header(True)-25
            text(line,545,y,9);y-=15
        y-=6
    c.save()
    return output.getvalue(),reference+'.pdf'
