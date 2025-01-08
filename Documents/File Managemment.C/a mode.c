#include<stdio.h>
#include<string.h>
int main()
{
FILE *fp;
fp=fopen("a.txt","a");
char s[10];
printf("enter data");
gets(s);
fputs(s,fp);
fprintf(fp,"\n%s",s);
fclose(fp);
return 0;
}