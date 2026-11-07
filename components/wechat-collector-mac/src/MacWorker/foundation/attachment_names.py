"""Bounded protobuf fields observed in local WCDB packed_info_data."""
import re


def fields(data):
    position=0;count=0
    def number():
        nonlocal position
        value=0
        for shift in range(0,70,7):
            if position>=len(data):raise ValueError('附件信息截断')
            byte=data[position];position+=1;value|=(byte&127)<<shift
            if not byte&128:return value
        raise ValueError('附件信息整数过长')
    while position<len(data):
        count+=1
        if count>256:raise ValueError('附件信息过于复杂')
        tag=number();field,wire=tag>>3,tag&7
        if not field:raise ValueError('附件信息字段无效')
        if wire==0:value=number()
        elif wire in (1,2,5):
            length=number() if wire==2 else (8 if wire==1 else 4)
            if length>len(data)-position:raise ValueError('附件信息长度无效')
            value=data[position:position+length];position+=length
        else:raise ValueError('附件信息编码不支持')
        yield field,wire,value


def packed_name(data):
    data=bytes(data or b'')
    if len(data)>65536:raise ValueError('附件信息过大')
    names=set()
    for field,wire,value in fields(data):
        if field!=3 or wire!=2:continue
        for nested,kind,name in fields(value):
            if nested!=4 or kind!=2:continue
            if not re.fullmatch(rb'[a-fA-F0-9]{32}',name):raise ValueError('附件文件名无效')
            names.add(name.decode('ascii').lower())
    if len(names)>1:raise ValueError('附件存在多个不同文件标识，无法唯一关联')
    return next(iter(names),None)
