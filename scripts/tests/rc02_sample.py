"""Synthetic structural reproduction for RELEASE-CANDIDATE-02, not a customer file.

Only the issue's declared shapes and edge-case values are reproduced. Product
identifiers/names and all unspecified columns are synthetic placeholders.
"""
import csv
import io

HEADERS = ['ARTICLENR','NAME','BARCODE','QUANTITY','LASTINITIALCOST','LISTPRICE','CURRENCYCODE'] + [f'SYNTHETIC_{i:02d}' for i in range(8,28)]
PRODUCTS = [
    ['RC02-001','Demó termék A','8,71999E+12','-35132','405,51','589,7637795','HUF'],
    ['RC02-002','Demó termék B','8,71716E+12','-710','120,00','170,10','HUF'],
    ['RC02-003','Demó termék C','5999000000017','-16920','77,5','99,9','HUF'],
]

def synthetic_feed():
    stream=io.StringIO(newline='')
    writer=csv.writer(stream,delimiter=';',lineterminator='\r\n')
    writer.writerow(HEADERS)
    writer.writerows(row+['']*20 for row in PRODUCTS)
    writer.writerows([['']*27]*4945)
    return stream.getvalue().encode('utf-8-sig')
