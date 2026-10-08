const documentTypes: Record<string,string> = {
  pdf:'application/pdf',txt:'text/plain',jpg:'image/jpeg',jpeg:'image/jpeg',png:'image/png',
};

export function prepareChatFiles(files:FileList, attached:number):File[] {
  if(files.length+attached>20)throw new Error('一次最多附加20份材料。');
  return Array.from(files,file=>{
    const extension=file.name.split('.').at(-1)?.toLowerCase() || '';
    const type=documentTypes[extension];
    if(!type)throw new Error(`${file.name} 暂不支持，请选择 PDF、TXT、JPG 或 PNG 文件。`);
    if(file.size===0)throw new Error(`${file.name} 是空文件，请重新选择。`);
    if(file.size>10*1024*1024)throw new Error(`${file.name} 超过10MB，请拆分后上传。`);
    // Mobile file providers may omit MIME types; the server still validates content.
    return file.type===type?file:new File([file],file.name,{type,lastModified:file.lastModified});
  });
}
