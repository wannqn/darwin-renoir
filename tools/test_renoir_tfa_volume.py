#!/usr/bin/env python3
"""Execute the actual PCM attenuation on full-scale input and every volume step."""
from pathlib import Path
import subprocess,tempfile
r=Path(__file__).resolve().parents[1];s=(r/'xnu/files/bsd/dev/renoir_tfa.c').read_text()
a=s.index('bool renoir_tfa_amp_volume(');b=s.index('void renoir_tfa_amp_quiesce(',a)
code='#include <stdint.h>\n#include <stdbool.h>\n#include <assert.h>\nstatic uint32_t tfa_pcm_scale;\n'+s[a:b]+r"""
int main(void){
 uint32_t previous=UINT32_MAX;
 for(unsigned level=0;level<=1000;level++){
  assert(renoir_tfa_amp_volume(level,0));assert(tfa_pcm_scale<=previous);previous=tfa_pcm_scale;
  int16_t samples[]={32767,-32768,0,0,16384,-16384};
  renoir_tfa_scale_pcm(samples,3);
  assert(samples[0]<=1037 && samples[1]>=-1038 && !samples[2] && !samples[3]);
  assert(samples[0]>=0 && samples[1]<=0);
  if(level>=960)assert(samples[0]==0);
 }
 renoir_tfa_amp_volume(0,0);uint32_t capped=tfa_pcm_scale;
 renoir_tfa_amp_volume(240,0);assert(tfa_pcm_scale==capped);
}
"""
with tempfile.TemporaryDirectory(prefix='tfa-volume-') as d:
 p=Path(d);(p/'test.c').write_text(code)
 subprocess.run(['clang','-Werror','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
print('TFA PCM volume: full-scale bounds, -30dB cap, monotonic attenuation, silence and integer overflow checks passed')
