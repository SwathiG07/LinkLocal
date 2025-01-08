#include<stdio.h>
#include<string.h>
#include<stdlib.h>

int main()
{
FILE *fp;
fp=fopen("a.txt","r");
char s[10];
char ch;
if(fp==NULL)
{
    printf("error");
    exit(1);
}
fseek(fp,5,SEEK_CUR);
while(!feof(fp))
{
ch=fgetc(fp);
printf("%c",ch);
}
rewind(fp);
while(!feof(fp))
{
ch=fgetc(fp);
printf("%c",ch);
}
}