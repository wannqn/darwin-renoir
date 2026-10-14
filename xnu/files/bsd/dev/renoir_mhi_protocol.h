/* MHI contexts have a 44-byte ABI, including unaligned 64-bit fields.
 * Layout follows OKX mhi_internal.h / mhi_init.c. Pure memory helpers,
 * shared with host tests; none of these functions can start device DMA.
 */
#ifndef RENOIR_MHI_PROTOCOL_H
#define RENOIR_MHI_PROTOCOL_H
struct renoir_mhi_context {
	uint32_t config, type, event;
	uint64_t base, length, rp, wp;
} __attribute__((packed, aligned(4)));
struct renoir_mhi_vector { uint64_t address, size; };
struct renoir_mhi_layout {
	uint32_t control, vectors, vector_size;
};
_Static_assert(sizeof(struct renoir_mhi_context)==44,"MHI context ABI");
_Static_assert(__builtin_offsetof(struct renoir_mhi_context,base)==12,"MHI base ABI");
_Static_assert(__builtin_offsetof(struct renoir_mhi_context,rp)==28,"MHI RP ABI");
_Static_assert(__builtin_offsetof(struct renoir_mhi_context,wp)==36,"MHI WP ABI");
_Static_assert(sizeof(struct renoir_mhi_vector)==16,"BHIE vector ABI");

static bool
renoir_mhi_make_layout(void *arena, uint32_t firmware_size, uint32_t allocation,
    uint64_t iova, struct renoir_mhi_layout *layout)
{
	if (!arena || !layout || ((uintptr_t)arena&3) || (iova&4095) ||
	    firmware_size<0x80000 || firmware_size>0x800000 || iova+allocation<iova) { return false; }
	uint32_t control=(firmware_size+16383)&~16383u;
	if (allocation<control+0x10000) { return false; }
	uint8_t *memory=arena;
	memset(memory+control,0,0x10000);
	struct renoir_mhi_context *channels=(void *)(memory+control);
	channels[20].type=1; channels[20].event=1;
	channels[21].type=2; channels[21].event=1;
	struct renoir_mhi_context *events=(void *)(memory+control+0x2000);
	for (unsigned i=0; i<2; i++) {
		events[i].type=1; /* valid event ring; MSI disabled, host polls */
		events[i].base=iova+control+(i ? 0x6000 : 0x5000);
		events[i].length=i ? 4096 : 512;
		events[i].rp=events[i].base;
		events[i].wp=events[i].base+events[i].length-16;
	}
	struct renoir_mhi_context *command=(void *)(memory+control+0x3000);
	command->base=iova+control+0x4000; command->length=128*16;
	command->rp=command->wp=command->base;
	struct renoir_mhi_vector *vectors=(void *)(memory+control+0x8000);
	unsigned count=0;
	for (uint32_t offset=0; offset<firmware_size; offset+=0x80000) {
		vectors[count].address=iova+offset;
		vectors[count].size=firmware_size-offset>0x80000 ? 0x80000 : firmware_size-offset;
		count++;
	}
	layout->control=control; layout->vectors=control+0x8000;
	layout->vector_size=count*sizeof(*vectors);
	return true;
}
/* QMI RESPOND_MEM TLV: count, then addr/size/type/restore (17 bytes).
 * Align each segment to its next power-of-two size, as Linux IOVA allocation does; reject the whole request before
 * publishing any address if its size, type or output bounds are invalid. */
static unsigned
renoir_mhi_memory_reply(uint8_t *out, unsigned capacity, const uint32_t *sizes,
    const uint32_t *types, unsigned count, uint64_t base, uint32_t available,
    uint32_t *used)
{
	if (!out || !sizes || !types || !used || !count || count>52 ||
	    capacity<4+17*count || (base&16383) || base+available<base) { return 0; }
	uint32_t total=0, offsets[52];
	for (unsigned i=0;i<count;i++) {
		if (!sizes[i] || sizes[i]>0x1000000 || types[i]>5) { return 0; }
		uint32_t rounded=(sizes[i]+16383)&~16383u, alignment=16384;
		while (alignment<sizes[i]) { alignment<<=1; }
		uint64_t aligned=(base+total+alignment-1)&~((uint64_t)alignment-1);
		if (aligned<base || aligned-base>available || rounded>available-(aligned-base)) { return 0; }
		offsets[i]=(uint32_t)(aligned-base);total=offsets[i]+rounded;
	}
	unsigned length=1+17*count;
	out[0]=1;out[1]=length;out[2]=length>>8;out[3]=count;
	for (unsigned i=0;i<count;i++) {
		uint8_t *record=out+4+17*i;
		uint64_t address=base+offsets[i];
		for (unsigned byte=0;byte<8;byte++) { record[byte]=address>>(byte*8); }
		for (unsigned byte=0;byte<4;byte++) {
			record[8+byte]=sizes[i]>>(byte*8); record[12+byte]=types[i]>>(byte*8);
		}
		record[16]=0; /* fresh, zeroed memory; no calibration restore claimed */
	}
	*used=total;
	return 4+17*count;
}
static void
renoir_qmi_u32_tlv(uint8_t *out, uint8_t tag, uint32_t value)
{
	out[0]=tag;out[1]=4;out[2]=0;
	for (unsigned byte=0;byte<4;byte++) { out[3+byte]=value>>(8*byte); }
}

/* QMI BDF_DOWNLOAD, same field order as ath11k qmi.c / OKX CNSS2. */
static unsigned
renoir_mhi_bdf_chunk(uint8_t *out, unsigned capacity, const uint8_t *data,
    unsigned length, uint32_t remaining, uint32_t segment, uint32_t board, unsigned type)
{
	if (!out || !data || !length || length>768 || length>remaining ||
	    capacity<length+38 || (type!=1 && type!=4)) { return 0; }
	out[0]=1;out[1]=1;out[2]=0;out[3]=1;
	renoir_qmi_u32_tlv(out+4,0x10,board);
	renoir_qmi_u32_tlv(out+11,0x11,remaining);
	renoir_qmi_u32_tlv(out+18,0x12,segment);
	out[25]=0x13;out[26]=length+2;out[27]=(length+2)>>8;
	out[28]=length;out[29]=length>>8;memcpy(out+30,data,length);
	uint8_t *tail=out+30+length;
	tail[0]=0x14;tail[1]=1;tail[2]=0;tail[3]=length==remaining;
	tail[4]=0x15;tail[5]=1;tail[6]=0;tail[7]=type;
	return length+38;
}
/* RDDM file records are 64 bytes; payloads follow the complete header.
 * Never trust firmware lengths or require a NUL-terminated file name. */
static const uint8_t *
renoir_rddm_sfr(const uint8_t *bytes, uint32_t length, uint32_t *reason_size)
{
	if (!reason_size) { return NULL; }*reason_size=0;
	if (!bytes || length<8) { return NULL; }
	uint32_t header;memcpy(&header,bytes+4,4);
	if (header<8 || header>8+6*64 || header>length || (header-8)%64) { return NULL; }
	uint32_t file=header;
	for (unsigned entry=8;entry<header;entry+=64) {
		uint64_t size;memcpy(&size,bytes+entry+16,8);
		if (size>length-file) { return NULL; }
		if (!memcmp(bytes+entry+44,"Q6-SFR.bin",11)) {
			*reason_size=(uint32_t)size;return bytes+file;
		}
		file+=(uint32_t)size;
	}
	return NULL;
}
#endif
