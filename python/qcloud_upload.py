# -*- coding=utf-8
import sys
import os
import logging
import optparse
import tarfile
import shutil
import requests
import datetime
import json
import hashlib
import hmac
import zipfile
import urllib
import math

# cos
from qcloud_cos import CosConfig
from qcloud_cos import CosS3Client
from qcloud_cos.cos_threadpool import SimpleThreadPool

# cdn
from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.cdn.v20180606 import cdn_client, models

# alibabacloud-tea
#import alibabacloud-tea import tea

# 正常情况日志级别使用INFO，需要定位时可以修改为DEBUG，此时SDK会打印和服务端的通信信息
logging.basicConfig(level=logging.ERROR, stream=sys.stdout)

# 设置用户属性, 包括 secret_id, secret_key, region等。Appid 已在CosConfig中移除，请在参数 Bucket 中带上 Appid。Bucket 由 BucketName-Appid 组成
# 替换为用户的 SecretId，请登录访问管理控制台进行查看和管理，https://console.cloud.tencent.com/cam/capi
secret_id = 'SecretId'
# 替换为用户的 SecretKey，请登录访问管理控制台进行查看和管理，https://console.cloud.tencent.com/cam/capi
secret_key = 'SecretKey'
# 如果使用永久密钥不需要填入token，如果使用临时密钥需要填入，临时密钥生成和使用指引参见https://cloud.tencent.com/document/product/436/14048
token = None
# 替换为用户的 region，已创建桶归属的region可以在控制台查看，https://console.cloud.tencent.com/cos5/bucket
# COS支持的所有region列表参见https://cloud.tencent.com/document/product/436/6224
bucketMap = {
    "domestic":{
        "region":'ap-guangzhou',
        "cdnPath": "https://xxx.xxx.com/"
    },
    "oversea":{
        "region":'na-ashburn',
        "cdnPath": "https://xx.xxx.com/"
    }
}
# 飞书通知webhook
feishuUrl = 'https://open.feishu.cn/open-apis/bot/v2/hook/xxxxx'

# 解压文件
def extractTarFile(fname, dirs="."):
    if not os.path.exists(fname):
        return ""

    bname = os.path.basename(fname)
    idx = bname.find(".tar.gz")
    if idx != -1:
        bname = bname[:idx]

    outDir = dirs + os.sep + bname
    if os.path.exists(outDir):
        shutil.rmtree(outDir)
    t = tarfile.open(fname)
    t.extractall(path = outDir)
    return outDir

def unzipFile(zip_src, dst_dir="."):
    bname = os.path.basename(zip_src)
    fname = os.path.splitext(bname)[0]
    fz = zipfile.ZipFile(zip_src, 'r')
    for file in fz.namelist():
        fz.extract(file, dst_dir+"/"+fname)
    idx = bname.find(".zip")
    if idx != -1:
        bname = bname[:idx]
    return dst_dir + os.sep + bname

def foreachDir(uploadDir, cosDir=""):
    apkPath, changeLog, versionCosKey = "", "", ""
    g = os.walk(uploadDir)

    fileDict = dict()
    for path, dir_list, file_list in g:
        for file_name in file_list:
            srcKey = os.path.join(path, file_name)

            cosObjectKey = ""
            idx = srcKey.find(uploadDir)
            if idx != -1:
                cosObjectKey = srcKey[idx+len(uploadDir):]
                cosObjectKey = cosObjectKey.replace("\\", "/")
                cosObjectKey = cosObjectKey.strip('/')
                if len(cosDir)>0:
                    cosObjectKey = cosDir+"/"+cosObjectKey

                # 判断是否是 apk 文件
                if os.path.splitext(file_name)[-1] == ".apk":
                    apkPath = cosObjectKey

                # changelog 文件
                if file_name.lower() == "changelog.txt":
                    changeLog = open(srcKey,'r',encoding='UTF-8').read()

                # version
                # if file_name.lower() == "version.txt":
                #     version = open(srcKey,'r',encoding='UTF-8').read()
                #if file_name.lower(os.path.splitext(file_name)[0]) == "version":
                if file_name.lower() == "version.json":
                    versionCosKey = cosObjectKey
                fileDict[srcKey] = cosObjectKey
    return fileDict, apkPath, changeLog, versionCosKey

# 多线程上传目录
def uploadFolder(bucket, uploadDir, cosDir):
    # 创建上传的线程池
    print("Start upload files")
    fileDict, apkPath, changeLog, versionCosKey = foreachDir(uploadDir, cosDir)

    pool = SimpleThreadPool()
    for srcKey,cosObjectKey in fileDict.items():
        print("upload %s --> %s" % (srcKey, cosObjectKey))
        pool.add_task(cosClient.upload_file, bucket, cosObjectKey, srcKey)

    # 等待线程上传线程结束
    pool.wait_completion()
    result = pool.get_result()
    ok = result['success_all']
    if not ok:
        print("Not all files upload sucessed. you should retry")
    else:
        print("All files upload sucessed.\n")
    return ok, fileDict, apkPath, changeLog, versionCosKey

# 上传单个文件
def uploadFile(bucket, filename, cosDir=""):
    cosObjectKey = os.path.basename(filename)
    if len(cosDir)>0:
        cosObjectKey = cosDir + "/" + cosObjectKey
    print("uploadFile %s --> %s" % (filename, cosObjectKey))
    cosClient.upload_file(bucket, cosObjectKey, filename)
    return True, {filename:cosObjectKey}

def refreshCDN(cdnPath, flushType="flush"):
    try:
        cred = credential.Credential(secret_id, secret_key)
        cdnClient = cdn_client.CdnClient(cred, "")

        req = models.PurgePathCacheRequest()
        req.Paths = [cdnPath]
        req.FlushType = flushType
        resp = cdnClient.PurgePathCache(req)

        print("CDN refresh sucessed")
        print(resp.to_json_string())
        return resp
    except TencentCloudSDKException as err:
        print("CDN refresh fail", err)

def pushCDNUrls(cdnPath, cosKeys, batchNum=500):
    resps = []
    try:
        cred = credential.Credential(secret_id, secret_key)
        cdnClient = cdn_client.CdnClient(cred, "")

        for i in range(0, len(cosKeys), batchNum):
            urls = []
            for j in range(0,batchNum):
                idx = i + j
                if idx >= len(cosKeys):
                    break
                else:
                    urls.append(cdnPath+cosKeys[idx])

            if len(urls)>0:
                req = models.PushUrlsCacheRequest()
                req.Urls = urls
                resp = cdnClient.PushUrlsCache(req)
                resps.append(resp)
                print("CDN push sucessed")
                print(resp.to_json_string())
    except TencentCloudSDKException as err:
        print("CDN push fail", err)
    return resps

def getVersion(cdnPath, versionCosKey):
    version = ""
    if len(versionCosKey) > 0:
        versionUrl = cdnPath+versionCosKey
        print("version url:", versionUrl)
        response = urllib.request.urlopen(versionUrl)
        if response:
            version = response.read().decode('utf-8')
            print("version:", version)
    return version

def hmacSha256(str):
    s = hashlib.sha256()
    s.update(str.encode())
    b = s.hexdigest().lower()
    return b

def hmac256(key, str):
    key = key.encode('utf-8')
    str = str.encode('utf-8')
    h = hmac.new(key, str, digestmod=hashlib.sha256)
    b = h.hexdigest().lower()
    return b

def refreshWangsuCDN(cdnPath):
    accessKey = "xxxx"
    secretKey = "xxxx"
    uri = "/ccm/purge/ItemIdReceiver"
    url = "https://open.chinanetcenter.com/ccm/purge/ItemIdReceiver"
    nowTimestamp = int(datetime.datetime.now().timestamp())
    nowTimestamp = str(nowTimestamp)
    data = {"dirs":[cdnPath]}
    # 创建request
    req = {
        "Method": "POST",
        "Uri": uri,
        "Url": url,
        "Host": "open.chinanetcenter.com",
        "SignedHeaders": "content-type;host",
        "Body": json.dumps(data),
    }

    headers = {
        "x-cnc-timestamp": nowTimestamp,
        "x-cnc-accessKey": accessKey,
        "x-cnc-auth-method": "AKSK",
        "Host": req["Host"],
        "Content-Type": "application/json",
    }

    canonicalKeys = []
    canonicalHeaders = {}
    keys = req["SignedHeaders"].split(";")
    for key, value in headers.items():
        canonicalHeaders[key.lower()] = value
    for key in keys:
        canonicalKeys.append(key)
        canonicalKeys.append(":")
        canonicalKeys.append(canonicalHeaders[key.lower()])
        canonicalKeys.append("\n")

    # 计算签名
    canonicalRequests = []
    canonicalRequests.append(req["Method"])
    canonicalRequests.append(uri)
    canonicalRequests.append("")
    canonicalRequests.append("".join(canonicalKeys))
    canonicalRequests.append(req["SignedHeaders"])
    canonicalRequests.append(hmacSha256(req["Body"]))
    canonicalRequest = "\n".join(canonicalRequests)
    stringToSign = "CNC-HMAC-SHA256" + "\n" + nowTimestamp + "\n" + hmacSha256(canonicalRequest)
    signature = hmac256(secretKey, stringToSign)

    # 计算Authorization
    authorization = [
        "CNC-HMAC-SHA256",
        " ",
        "Credential=",
        accessKey,
        ", ",
        "SignedHeaders=",
        req["SignedHeaders"],
        ", ",
        "Signature=",
        signature
    ]
    headers["Authorization"] = "".join(authorization)
    resp = requests.post(url=url, headers=headers, json=data)
    print(resp.text)

def notifyFeiShu(apkKey, changeLog, tarball, cdnPath, cdnResults, cdnVersion):
    basename = os.path.basename(tarball)
    s = basename.split("-")
    contents = [
        "发布文件：" + tarball,
        "发布时间：" + datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    ]
    if len(s) > 1:
        contents.append("发布类型：" + ("全包" if s[0]=="bin" else "补丁包"))
        contents.append("分支：" + s[1])
        contents.append("平台：" + s[2])
        contents.append("版本：" + s[3])
    if len(cdnVersion) > 0:
        contents.append("cdn版本："+cdnVersion)
    for result in cdnResults:
        contents.append("cdn地址：%s"%(result["cdn"]))
        for resp in result["resps"]:
            contents.append("  - cdn%sTaskId：%s, RequestId：%s"%(result["type"], resp.TaskId, resp.RequestId))
    if len(changeLog) > 0:
        contents.append("\n更新内容：")
        contents.append(changeLog)
    if len(apkKey) > 0:
        cdnURL = cdnPath + apkKey
        contents.append("\n下载地址：")
        contents.append(cdnURL)
        contents.append("\n二维码地址：")
        contents.append("https://api.qrserver.com/v1/create-qr-code/?size=250x250&data="+cdnURL)

    # 发送飞书
    contestsStr = "\n".join(contents)
    headers = { "Content-Type": "application/json"}
    req_body = {
        "content": {"text": contestsStr},
        "msg_type": "text",
    }
    r = requests.post(url=feishuUrl, headers=headers, json=req_body)
    #print(r)
    #print(r.text)
    #print(r.content)

def main():
    usage = "Usage: python3 %prog [options]\n\t e.g: python3 %prog --bucket=examplebucket-1250000000 --tarball=xxx.tar.gz  [--exdir=.] [--platform=oversea]"
    parser = optparse.OptionParser(usage=usage)
    parser.add_option("--bucket", dest="bucket", help="[required] bucket name")
    parser.add_option("--tarball", dest="tarball", help="[required] upload tarball")
    parser.add_option("--exdir", dest="exdir", default=".", help="[option] extract files into exdir")
    parser.add_option("--cosdir", dest="cosdir", default="", help="[option] upload files into cosdir")
    parser.add_option("--platform", dest="platform", default="oversea", help="[option] cot bucket platform")
    parser.add_option("--silent", dest="silent", action="store_true", help="[option] don't send feishu notifications")
    parser.add_option("--push", dest="push", action="store_true", help="[option] push cdn")

    options, args = parser.parse_args()
    requireds = ["bucket", "tarball"]
    for opt in requireds:
        if options.__dict__.get(opt) is None:
            parser.print_help()
            return

    # 获取配置对象
    global cosClient
    bucketInfo = bucketMap[options.platform]
    config = CosConfig(Region=bucketInfo["region"], SecretId=secret_id, SecretKey=secret_key, Token=token)
    cosClient = CosS3Client(config)

    uploadDir = ""
    isMultiFile = True
    srcFile = options.tarball
    cosDir = options.cosdir
    if os.path.isfile(srcFile):
        # file
        if tarfile.is_tarfile(srcFile):
            # tar.gz
            uploadDir = extractTarFile(srcFile, options.exdir)
        elif zipfile.is_zipfile(srcFile):
            # zip
            uploadDir = unzipFile(srcFile, options.exdir)
        else:
            # single file
            isMultiFile = False
    elif os.path.isdir(srcFile):
        # dir
        uploadDir = os.path.abspath(srcFile)
        cosDir = os.path.basename(srcFile) if len(cosDir)==0 else cosDir
    else:
        print("invalid tarball")
        return

    # 上传到cos
    ok, fileDict, apkPath, changeLog, versionCosKey = False, None, "", "", ""
    if isMultiFile:
        if len(uploadDir) == 0:
            print("invalid tarball option")
            return
        print("upload dir:", uploadDir)
        ok, fileDict, apkPath, changeLog, versionCosKey = uploadFolder(options.bucket, uploadDir, cosDir)
    else:
        ok, fileDict = uploadFile(options.bucket, srcFile, cosDir)

    if ok:
        # 获取根目录
        rootDir = ""
        for _, value in fileDict.items():
            s = value.split("/")
            if len(s) > 1:
                rootDir = s[0]
            else:
                rootDir = ""
                break
        sep = "" if len(rootDir)==0 else "/"

        # 刷新cdn
        cdnResults = []
        cdnPath = bucketInfo["cdnPath"]
        if options.platform == "oversea":
            for cdn in cdnPath:
                refreshWangsuCDN(cdn)
        else:
            cosKeys = list(fileDict.values())
            #if isinstance(cdnPath, list):
            resp = refreshCDN(cdnPath + rootDir + sep)
            cdnResults.append({"type": "刷新", "cdn":cdnPath + rootDir + sep, "resps":[resp]})
            if options.push:
                # 全部预热
                resps = pushCDNUrls(cdnPath, cosKeys)
                cdnResults.append({"type": "预热", "cdn":cdnPath, "resps":resps})
            elif len(versionCosKey)>0:
                # 预热version文件
                resp = pushCDNUrls(cdnPath, [versionCosKey])
                cdnResults.append({"type": "预热version文件", "cdn":cdnPath + versionCosKey, "resps":[resp]})
            print()

        # 预热version
        version = getVersion(cdnPath, versionCosKey)

        if not options.silent:
            notifyFeiShu(apkPath, changeLog, options.tarball, cdnPath, cdnResults, version)

if __name__ == "__main__":
    main()
