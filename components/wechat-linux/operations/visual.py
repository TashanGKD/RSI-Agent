"""Stable attachment identity area; caret and empty editor are separate components."""
def attachment_box(image,bounds):
 im=image.crop(tuple(bounds)).convert('RGB');w,h=im.size
 if w*h>500000:raise ValueError('attachment region over budget')
 mask=bytearray(1 if min(p)<245 else 0 for p in im.getdata());components=[]
 for index in range(len(mask)):
  if not mask[index]:continue
  mask[index]=0;stack=[index];n=0;x0=w;y0=h;x1=0;y1=0
  while stack:
   p=stack.pop();y,x=divmod(p,w);n+=1;x0=min(x0,x);y0=min(y0,y);x1=max(x1,x);y1=max(y1,y)
   for q in ([p-1] if x else [])+([p+1] if x+1<w else [])+([p-w] if y else [])+([p+w] if y+1<h else []):
    if mask[q]:mask[q]=0;stack.append(q)
  if n>=300 and x1-x0>40 and y1-y0>25:components.append((n,[bounds[0]+x0,bounds[1]+y0,bounds[0]+x1+1,bounds[1]+y1+1]))
 if not components:raise ValueError('no unambiguous substantial attachment card')
 components.sort(reverse=True)
 if len(components)>1 and components[1][0]>.8*components[0][0]:raise ValueError('ambiguous attachment content')
 x0,y0,x1,y1=components[0][1]
 # Exclude two pixels of widget chrome. Exact interior comparison remains strict;
 # the native file MD5/name/size check independently proves the actual attachment.
 return [x0+2,y0+2,x1-2,y1-2]
