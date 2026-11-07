using System;
using System.IO;
using System.IO.Compression;
using System.Text;
using System.Threading;
using WechatUiCollector.Storage;
namespace WechatUiCollector.WechatDb;
public static partial class RawContentCodec
{
    internal static BoundedRawContent DecompressBounded(object? stored,int maximumCompressedBytes,int maximumDecodedBytes,CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        if(maximumCompressedBytes is <1 or >65536 || maximumDecodedBytes is <1 or >262144) throw new ArgumentOutOfRangeException(nameof(maximumDecodedBytes));
        if(stored is null or DBNull) return new(BoundedRawOutcome.Missing,null,0,0);
        if(stored is not byte[] bytes) return new(BoundedRawOutcome.InvalidStorage,null,0,0);
        if(bytes.Length>maximumCompressedBytes) return new(BoundedRawOutcome.CompressedLimit,null,0,0);
        if(bytes.Length<6)return new(BoundedRawOutcome.Corrupt,null,bytes.Length,0);
        try {
            using var input=new MemoryStream(bytes,false);using var zip=new ZLibStream(input,CompressionMode.Decompress);
            using var output=new MemoryStream(Math.Min(maximumDecodedBytes,4096));byte[] block=new byte[Math.Min(maximumDecodedBytes+1,4096)];int used=0;
            while(true) {
                token.ThrowIfCancellationRequested();int count=zip.Read(block,0,Math.Min(block.Length,maximumDecodedBytes-used+1));
                if(count==0)break;if(count>maximumDecodedBytes-used)return new(BoundedRawOutcome.DecodedLimit,null,bytes.Length,maximumDecodedBytes);
                output.Write(block,0,count);used+=count;
            }
            token.ThrowIfCancellationRequested();string text=new UTF8Encoding(false,true).GetString(output.GetBuffer(),0,used);
            return new(BoundedRawOutcome.Ready,text,bytes.Length,used);
        }
        catch(DecoderFallbackException) { return new(BoundedRawOutcome.InvalidUtf8,null,bytes.Length,0); }
        catch(InvalidDataException) { return new(BoundedRawOutcome.Corrupt,null,bytes.Length,0); }
    }
}
