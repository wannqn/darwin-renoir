/* PM8350B finite PATTERN1 tap. RAM/register settings only, no SDAM/PBS/OTP. */
#ifndef RENOIR_HAPTIC_CORE_H
#define RENOIR_HAPTIC_CORE_H
struct rhh_bus {bool (*read)(uint16_t,uint8_t *);bool (*write)(uint16_t,uint8_t);};
struct rhh_saved {uint16_t reg;uint8_t value;};
struct rhh_state {struct rhh_saved saved[48];unsigned count;bool ready,playing;uint16_t failed_reg;};
static bool rhh_allowed(uint16_t r) {
 return r==0xf046 || r==0xf048 || r==0xf049 || r==0xf04c || r==0xf05c || r==0xf05d ||
        r==0xf063 || r==0xf068 || r==0xf072 || r==0xf130 || r==0xf131 || (r>=0xf134 && r<=0xf14b);
}
static bool rhh_write(struct rhh_state *s,const struct rhh_bus *b,uint16_t reg,uint8_t value) {
 s->failed_reg=reg;uint8_t old,actual;if(!rhh_allowed(reg) || !b->read(reg,&old))return false;
 unsigned i;for(i=0;i<s->count;i++)if(s->saved[i].reg==reg)break;
 if(i==s->count){if(i==48)return false;s->saved[s->count++]=(struct rhh_saved){reg,old};}
 bool ok=b->write(reg,value) && b->read(reg,&actual) && actual==value;
 if(ok)s->failed_reg=0;return ok;
}
static bool rhh_restore(struct rhh_state *s,const struct rhh_bus *b) {
 if(!s->count){s->ready=false;s->playing=false;return true;}
 bool ok=b->write(0xf04c,2);uint8_t v;
 if(!b->read(0xf04c,&v) || (v&0x80))ok=false;
 while(s->count){struct rhh_saved a=s->saved[--s->count];
  if(!b->write(a.reg,a.value) || !b->read(a.reg,&v) || v!=a.value)ok=false;
 }
 s->ready=false;s->playing=false;return ok;
}
static bool rhh_prepare(struct rhh_state *s,const struct rhh_bus *b,uint32_t bob_mv,bool bob_on) {
 uint8_t type,sub,rev,play,fault;
 if(!bob_on || bob_mv<2900 || bob_mv>3960)return false;
 if(!b->read(0xf004,&type)||type!=0x15 || !b->read(0xf005,&sub)||sub!=0x0a ||
    !b->read(0xf001,&rev)||rev!=2 || !b->read(0xf104,&type)||type!=0x15 ||
    !b->read(0xf105,&sub)||sub!=0x0b || !b->read(0xf101,&rev)||rev!=2 ||
    !b->read(0xf04c,&play)||(play&0x80) || !b->read(0xf00c,&fault)||(fault&7))return false;
 /* Voltage below the live Android2450mV setting; eight samples, no loop. */
 if(!rhh_write(s,b,0xf04c,2) || !rhh_write(s,b,0xf048,33))return false;
 uint8_t old;
 if(!b->read(0xf049,&old)||!rhh_write(s,b,0xf049,(old&~0x13u)|1))return false;
 if(!b->read(0xf063,&old)||!rhh_write(s,b,0xf063,old&~0x80u))return false;
 /* External supply path and RC-clock mode as Android configures them. */
 if(!b->read(0xf068,&old)||!rhh_write(s,b,0xf068,old|1))return false;
 if(!b->read(0xf072,&old)||!rhh_write(s,b,0xf072,(old&~12u)|4))return false;
 /* Android's live calibrated open-loop period, 0x3ec x5us before RC adjustment. */
 if(!rhh_write(s,b,0xf05c,3)||!rhh_write(s,b,0xf05d,0xec) ||
    !rhh_write(s,b,0xf130,3)||!rhh_write(s,b,0xf131,0xec))return false;
 static const uint16_t sample[]={0x1f,0x3f,0x5f,0x7f,0x17f,0x15f,0x13f,0x11f};
 for(unsigned i=0;i<8;i++)if(!rhh_write(s,b,0xf134+i*3,0) ||
    !rhh_write(s,b,0xf135+i*3,sample[i]>>8) || !rhh_write(s,b,0xf136+i*3,sample[i]))return false;
 if(!b->read(0xf046,&old)||!rhh_write(s,b,0xf046,old|0x80))return false;
 s->ready=true;return true;
}
static bool rhh_start(struct rhh_state *s,const struct rhh_bus *b) {
 uint8_t fault;
 if(!s->ready || !b->read(0xf00c,&fault)||(fault&7))return false;
 s->playing=rhh_write(s,b,0xf04c,0x82);return s->playing;
}
static bool rhh_stop(struct rhh_state *s,const struct rhh_bus *b) {
 bool ok=rhh_write(s,b,0xf04c,2);s->playing=false;return ok;
}
#endif
