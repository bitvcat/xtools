# -*- coding=utf-8
from genericpath import isfile
import time
from queue import Queue
from unicodedata import name
from urllib import response
import requests
import threading
import json
import os
import urllib3

savepath = "emoji"
def getEmojiList():
    response = requests.get("https://api.github.com/emojis", verify=False)
    #print(response.content)
    emojis = json.loads(response.content)
    return emojis

# 保存图片至指定页面
def save_image(q):
    while not q.empty():
        name = q.get()
        #print("emoji name: " + name)
        imgname = savepath + '\\'+name+'.png'
        if not os.path.isfile(imgname):
            url = "https://github.githubassets.com/images/icons/emoji/"+name+".png"
            img_response = requests.get(url, verify=False)
            with open(imgname, 'wb') as file:
                print("save emoji: " + name)
                file.write(img_response.content)

if __name__ == '__main__':
    urllib3.disable_warnings()# 等价于requests.packages.urllib3.disable_warnings()
    if not os.path.exists(savepath):
        os.makedirs(savepath)

    startTime = time.time()
    emojis = getEmojiList()
    keys = list(emojis.keys())
    print("emoji len: %d" % len(keys))

    # queue
    key_queue = Queue()
    for key in emojis:
        key_queue.put(key)

    threads = []
    for i in range(10):
        t = threading.Thread(target=save_image, args=(key_queue,))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()
    print(time.time() - startTime)
