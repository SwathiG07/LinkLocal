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
/*
fgets(s,2,fp);
printf("%s",s);
while(!feof(fp))
{
ch=fgetc(fp);
printf("%c",ch);
}
printf("\n");*/
while(!feof(fp))
{
fgets(s,6,fp);
printf("%s",s);
}
fclose(fp);
return 0;
}