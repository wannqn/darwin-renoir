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
  assert(samples[0]<=3277 && samples[1]>=-3278 && !samples[2] && !samples[3]);
  assert(samples[0]>=0 && samples[1]<=0);
  if(level>=960)assert(samples[0]==0);
 }
 renoir_tfa_amp_volume(0,0);uint32_t capped=tfa_pcm_scale;
 renoir_tfa_amp_volume(160,0);assert(tfa_pcm_scale==capped);
 renoir_tfa_amp_volume(240,0);uint32_t quiet=tfa_pcm_scale;
 renoir_tfa_amp_volume(192,0);assert(tfa_pcm_scale>(uint64_t)quiet*199/100 && tfa_pcm_scale<(uint64_t)quiet*201/100);
 renoir_tfa_amp_volume(160,0);assert(tfa_pcm_scale>(uint64_t)quiet*315/100 && tfa_pcm_scale<(uint64_t)quiet*317/100);
}
"""
with tempfile.TemporaryDirectory(prefix='tfa-volume-') as d:
 p=Path(d);(p/'test.c').write_text(code)
 subprocess.run(['clang','-Werror','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
print('TFA PCM volume: full-scale bounds, -20dB cap and +6/+10dB steps, monotonic attenuation, silence and integer overflow checks passed')

# Upstream's +12dB compensation must still obey the final Renoir PCM ceiling.
import shutil
with tempfile.TemporaryDirectory(prefix='tfa-guard-volume-') as d:
 p=Path(d);(p/'sys').mkdir();shutil.copy2(r/'xnu/files/bsd/sys/redwood_audio.h',p/'sys/redwood_audio.h')
 (p/'sys/ioccom.h').write_text('#define _IOW(g,n,t) 0\n')
 combined=code[:code.index('int main(void)')]+r"""
void redwood_guard_configure(bool,uint32_t);
void redwood_guard_attenuation(uint32_t);
void redwood_guard_process(int16_t *,uint32_t);
int main(void){
 for(unsigned attenuation=160;attenuation<=240;attenuation+=32){
  redwood_guard_configure(true,96);redwood_guard_attenuation(attenuation);
  assert(renoir_tfa_amp_volume(attenuation,0));
  for(unsigned block=0;block<200;block++){
   int16_t samples[1920];
   for(unsigned i=0;i<1920;i++)samples[i]=(int16_t)((i*997u+block*73u)&65535);
   redwood_guard_process(samples,960);renoir_tfa_scale_pcm(samples,960);
   for(unsigned i=0;i<1920;i++)assert(samples[i]<=3277 && samples[i]>=-3278);
  }
 }
}
"""
 (p/'combined.c').write_text(combined)
 subprocess.run(['clang','-O2','-DKERNEL','-I'+str(p),str(p/'combined.c'),str(r/'xnu/files/bsd/dev/redwood_guard.c'),'-o',str(p/'combined')],check=True)
 subprocess.run([str(p/'combined')],check=True)
print('TFA + actual upstream guard: +12dB compensation remains within the final PCM ceiling')
