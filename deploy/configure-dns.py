"""Register only sportswise.waywise.tech using existing DNSPod permissions. Run on server."""
import hashlib
import hmac
import json
import socket
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def load(path):
    return {k.strip():v.strip().strip('\"\'') for line in Path(path).read_text().splitlines()
            if '=' in line and not line.lstrip().startswith('#') for k,_,v in [line.partition('=')]}


def call(env,action,params):
    endpoint='dnspod.tencentcloudapi.com';service='dnspod'
    body=json.dumps(params,ensure_ascii=False,separators=(',',':')).encode()
    stamp=int(time.time());day=datetime.fromtimestamp(stamp,timezone.utc).strftime('%Y-%m-%d')
    sha=lambda b:hashlib.sha256(b).hexdigest()
    canonical=f'POST\n/\n\ncontent-type:application/json; charset=utf-8\nhost:{endpoint}\n\ncontent-type;host\n{sha(body)}'
    scope=f'{day}/{service}/tc3_request'
    to_sign=f'TC3-HMAC-SHA256\n{stamp}\n{scope}\n{sha(canonical.encode())}'
    mac=lambda k,s:hmac.new(k,s.encode(),hashlib.sha256).digest()
    signing=mac(mac(mac(('TC3'+env['TENCENTCLOUD_SECRET_KEY']).encode(),day),service),'tc3_request')
    signature=hmac.new(signing,to_sign.encode(),hashlib.sha256).hexdigest()
    req=urllib.request.Request('https://'+endpoint,data=body,headers={
        'Content-Type':'application/json; charset=utf-8','Host':endpoint,
        'Authorization':f"TC3-HMAC-SHA256 Credential={env['TENCENTCLOUD_SECRET_ID']}/{scope}, SignedHeaders=content-type;host, Signature={signature}",
        'X-TC-Action':action,'X-TC-Timestamp':str(stamp),'X-TC-Version':'2021-03-23'})
    with urllib.request.urlopen(req,timeout=20) as response:
        result=json.load(response)['Response']
    if 'Error' in result:
        error=result['Error']
        if action=='DescribeRecordList' and error['Code']=='ResourceNotFound.NoDataOfRecord':return {'RecordList':[]}
        raise RuntimeError(error['Code']+': '+error['Message'])
    return result


if __name__=='__main__':
    env=load(sys.argv[1])
    records=call(env,'DescribeRecordList',{'Domain':'waywise.tech','Subdomain':'sportswise','Limit':100}).get('RecordList',[])
    matches=[r for r in records if r['Name']=='sportswise']
    if matches:
        target=socket.gethostbyname('waywise.tech')
        if not all((r['Type']=='CNAME' and r['Value'].rstrip('.')=='waywise.tech') or (r['Type']=='A' and r['Value']==target) for r in matches):
            raise SystemExit('Existing SportsWise DNS points elsewhere; left unchanged')
        print('SportsWise DNS already configured')
    else:
        call(env,'CreateRecord',{'Domain':'waywise.tech','SubDomain':'sportswise','RecordType':'CNAME','RecordLine':'默认','Value':'waywise.tech.','TTL':600})
        print('SportsWise DNS created')
